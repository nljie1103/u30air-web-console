package main

import (
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
)

// Host CLI scripts only stage files. The device runs one shared transaction,
// which also allows recovery to proceed if the host ADB connection disappears.
func copyFile(src, dst string, mode os.FileMode) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.OpenFile(dst+".part", os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	defer os.Remove(dst + ".part")
	_, err = io.Copy(out, in)
	closeErr := out.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	if err = os.Chmod(dst+".part", mode); err != nil {
		return err
	}
	return os.Rename(dst+".part", dst)
}

func runningEndpoint(id serviceIdentity) (string, error) {
	b, err := os.ReadFile(fmt.Sprintf("/proc/%d/cmdline", id.PID))
	if err != nil {
		return "", err
	}
	args := strings.Split(string(b), "\x00")
	if len(args) < 5 || args[1] != "-listen" {
		return "", errors.New("invalid old service arguments")
	}
	host, port, err := net.SplitHostPort(args[2])
	ip := net.ParseIP(host)
	n, e := strconv.Atoi(port)
	if err != nil || e != nil || ip == nil || ip.To4() == nil || !ip.IsPrivate() || n < 1024 || n > 65535 {
		return "", errors.New("invalid old listener")
	}
	return args[2], nil
}

func launchManaged(state, addr string) (*exec.Cmd, error) {
	out, err := os.OpenFile(filepath.Join(state, "server.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0600)
	if err != nil {
		return nil, err
	}
	defer out.Close()
	cmd := exec.Command(filepath.Join(state, "current"), "-listen", addr, "-state-dir", state)
	cmd.Stdout = out
	cmd.Stderr = out
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err = cmd.Start(); err != nil {
		return nil, err
	}
	return cmd, nil
}

func cliDeploy(state, addr, ver string) error {
	if !releaseTagRe.MatchString("v"+ver) || ver != version {
		return errors.New("invalid candidate version")
	}
	lock, err := acquireMaintenance(state)
	if err != nil {
		return errors.New("service is busy")
	}
	defer lock.Close()
	marker := filepath.Join(state, "deployment-recovery")
	if _, err = os.Stat(marker); !os.IsNotExist(err) {
		return errors.New("unresolved deployment recovery; preserve backups")
	}
	targetRel := filepath.Join("releases", ver, "desktopd")
	target := filepath.Join(state, targetRel)
	previous, err := os.Readlink(filepath.Join(state, "current"))
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	if previous != "" && !releasePathRE.MatchString(previous) {
		return errors.New("invalid old version pointer")
	}
	// Never interrupt a service whose persisted authentication is unreadable.
	if _, e := os.Stat(filepath.Join(state, "auth.json")); e == nil {
		if _, e = loadAuthConfig(state, ""); e != nil {
			return fmt.Errorf("authentication configuration unreadable: %w", e)
		}
	} else if !os.IsNotExist(e) {
		return e
	} else if previous != "" {
		password, e := os.ReadFile(filepath.Join(state, "password.txt"))
		if e != nil || strings.TrimSuffix(string(password), "\n") == "" {
			return errors.New("legacy authentication configuration unreadable")
		}
	}
	if previous == targetRel {
		return errors.New("same version already installed")
	}
	oldID, err := readServiceIdentity(state)
	oldAddr := ""
	if err == nil {
		if previous == "" || oldID.Exe != filepath.Join(state, previous) {
			return errors.New("old service identity mismatch")
		}
		oldAddr, err = runningEndpoint(oldID)
		if err != nil {
			return err
		}
	} else if !os.IsNotExist(err) {
		return err
	}
	scripts := []string{"start.sh", "stop.sh"}
	for _, name := range scripts {
		if _, err = os.Stat(filepath.Join(state, name+".next")); err != nil {
			return err
		}
		if _, err = os.Stat(filepath.Join(state, name+".rollback")); !os.IsNotExist(err) {
			return errors.New("unresolved script backup")
		}
	}
	if previous != "" {
		for _, name := range scripts {
			if err = copyFile(filepath.Join(state, name), filepath.Join(state, name+".rollback"), 0700); err != nil {
				return err
			}
		}
	}
	if err = os.WriteFile(marker, []byte(previous+"\n"+oldAddr+"\n"), 0600); err != nil {
		return err
	}
	finished := false
	defer func() {
		if finished {
			for _, name := range scripts {
				_ = os.Remove(filepath.Join(state, name+".rollback"))
			}
			_ = os.Remove(marker)
		}
	}()
	var child *exec.Cmd
	runErr := func() error {
		if oldAddr != "" {
			if e := stopIdentity(oldID); e != nil {
				return e
			}
		}
		for _, name := range []string{"server.pid", "server.identity"} {
			_ = os.Remove(filepath.Join(state, name))
		}
		if e := os.Rename(target+".next", target); e != nil {
			return e
		}
		for _, name := range scripts {
			if e := os.Rename(filepath.Join(state, name+".next"), filepath.Join(state, name)); e != nil {
				return e
			}
		}
		if e := symlinkSwap(state, targetRel); e != nil {
			return e
		}
		child, err = launchManaged(state, addr)
		if err != nil {
			return err
		}
		if !waitHealth(addr, ver, 20) {
			return errors.New("new service health check failed")
		}
		return child.Process.Release()
	}()
	if runErr == nil {
		finished = true
		fmt.Println("Deployment health check passed: " + addr)
		return nil
	}
	// A child process handle identifies exactly the process we launched; never
	// signal an arbitrary pidfile after a failed start.
	if child != nil {
		_ = child.Process.Kill()
		_ = child.Wait()
	}
	if oldAddr != "" {
		// If stop failed while the old instance was still alive, leave its
		// identity and original files untouched; restoration is manual.
		if current, e := processIdentity(oldID.PID); (e == nil && current == oldID) || (e != nil && !os.IsNotExist(e)) {
			return fmt.Errorf("old service still running; recovery files retained: %w", runErr)
		}
	}
	for _, name := range []string{"server.pid", "server.identity"} {
		_ = os.Remove(filepath.Join(state, name))
	}
	if previous == "" {
		_ = os.Remove(filepath.Join(state, "current"))
		finished = true
		return runErr
	}
	for _, name := range scripts {
		if e := copyFile(filepath.Join(state, name+".rollback"), filepath.Join(state, name), 0700); e != nil {
			return fmt.Errorf("restore failed; backups retained: %w", e)
		}
	}
	if e := symlinkSwap(state, previous); e != nil {
		return e
	}
	if oldAddr != "" {
		restored, e := launchManaged(state, oldAddr)
		if e != nil {
			return e
		}
		_ = restored.Process.Release()
		if !waitHealth(oldAddr, strings.Split(previous, "/")[1], 20) {
			return errors.New("old service recovery not healthy; backups retained")
		}
	}
	finished = true
	return fmt.Errorf("new deployment failed; previous version restored: %w", runErr)
}
