package main

import (
	"bytes"
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"

	"golang.org/x/sys/unix"
)

type serviceIdentity struct {
	PID   int
	Start string
	Exe   string
}

//go:embed deploy/start.sh deploy/stop.sh
var serviceScripts embed.FS

func syncServiceScripts(state string) error {
	for _, name := range []string{"start.sh", "stop.sh"} {
		data, err := serviceScripts.ReadFile("deploy/" + name)
		if err != nil {
			return err
		}
		path := filepath.Join(state, name)
		if old, e := os.ReadFile(path); e == nil && bytes.Equal(old, data) {
			continue
		}
		if err = os.WriteFile(path+".sync", data, 0700); err != nil {
			return err
		}
		if err = os.Chmod(path+".sync", 0700); err != nil {
			return err
		}
		if err = os.Rename(path+".sync", path); err != nil {
			return err
		}
	}
	return nil
}

var releasePathRE = regexp.MustCompile("^releases/[0-9]+[.][0-9]+[.][0-9]+/desktopd$")

func processIdentity(pid int) (serviceIdentity, error) {
	if pid <= 1 {
		return serviceIdentity{}, errors.New("invalid service PID")
	}
	dir := fmt.Sprintf("/proc/%d", pid)
	data, err := os.ReadFile(dir + "/stat")
	if err != nil {
		return serviceIdentity{}, err
	}
	i := strings.LastIndexByte(string(data), ')')
	if i < 0 {
		return serviceIdentity{}, errors.New("invalid process stat")
	}
	fields := strings.Fields(string(data[i+1:]))
	if len(fields) < 20 || fields[0] == "Z" {
		return serviceIdentity{}, os.ErrNotExist
	}
	exe, err := os.Readlink(dir + "/exe")
	if err != nil {
		return serviceIdentity{}, err
	}
	return serviceIdentity{PID: pid, Start: fields[19], Exe: exe}, nil
}

func servicePath(state, exe string) bool {
	rel, err := filepath.Rel(state, exe)
	return err == nil && releasePathRE.MatchString(rel)
}

func writeServiceIdentity(state string) error {
	id, err := processIdentity(os.Getpid())
	if err != nil {
		return err
	}
	// Allow explicitly launched developer binaries, but only managed release
	// paths can be stopped via the management scripts.
	b, err := json.Marshal(id)
	if err != nil {
		return err
	}
	if err = os.WriteFile(filepath.Join(state, "server.identity"), b, 0600); err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(state, "server.pid"), []byte(strconv.Itoa(id.PID)+"\n"), 0600)
}

func readServiceIdentity(state string) (serviceIdentity, error) {
	b, err := os.ReadFile(filepath.Join(state, "server.pid"))
	if err != nil {
		return serviceIdentity{}, err
	}
	pid, err := strconv.Atoi(strings.TrimSpace(string(b)))
	if err != nil || pid <= 1 {
		return serviceIdentity{}, errors.New("invalid PID file")
	}
	id, err := processIdentity(pid)
	if err != nil {
		return serviceIdentity{}, err
	}
	if !servicePath(state, id.Exe) {
		return serviceIdentity{}, errors.New("PID does not belong to a managed release")
	}
	// Legacy daemons do not write an identity file. A prior failed
	// migration may have left a newer instance's record; only permit this
	// exception when the running executable is an actual legacy release.
	rel, _ := filepath.Rel(state, id.Exe)
	major, _ := strconv.Atoi(strings.Split(strings.Split(rel, "/")[1], ".")[0])
	b, err = os.ReadFile(filepath.Join(state, "server.identity"))
	if err == nil && major >= 3 {
		var recorded serviceIdentity
		if json.Unmarshal(b, &recorded) != nil || recorded != id {
			return serviceIdentity{}, errors.New("service instance identity mismatch")
		}
	} else if err != nil {
		if !os.IsNotExist(err) {
			return serviceIdentity{}, err
		}
		if major >= 3 {
			return serviceIdentity{}, errors.New("running service identity record missing")
		}
	}
	// Legacy server.pid files are accepted only for exact managed executable and arguments.
	cmd, err := os.ReadFile(fmt.Sprintf("/proc/%d/cmdline", pid))
	if err != nil {
		return serviceIdentity{}, err
	}
	args := strings.Split(string(cmd), "\x00")
	if len(args) < 5 || (args[0] != filepath.Join(state, "current") && args[0] != id.Exe) {
		return serviceIdentity{}, errors.New("service argv mismatch")
	}
	if args[1] != "-listen" || args[3] != "-state-dir" || args[4] != state {
		return serviceIdentity{}, errors.New("service arguments mismatch")
	}
	return id, nil
}

func stopIdentity(id serviceIdentity) error {
	// pidfd prevents signaling a reused PID on supported kernels.
	fd, err := unix.PidfdOpen(id.PID, 0)
	if err == nil {
		defer unix.Close(fd)
	} else if !errors.Is(err, unix.ENOSYS) && !errors.Is(err, unix.EINVAL) && !errors.Is(err, unix.EPERM) && !errors.Is(err, unix.EACCES) {
		if errors.Is(err, unix.ESRCH) {
			return nil
		}
		return err
	}
	current, e := processIdentity(id.PID)
	if os.IsNotExist(e) {
		return nil
	}
	if e != nil {
		return e
	}
	if current != id {
		return errors.New("service PID reused; refusing to signal")
	}
	if fd >= 0 && err == nil {
		e = unix.PidfdSendSignal(fd, unix.SIGTERM, nil, 0)
	} else {
		// Older Android kernels do not provide pidfd. Revalidate immediately
		// before signaling; refuse any changed identity.
		current, e = processIdentity(id.PID)
		if e != nil || current != id {
			return errors.New("service identity changed")
		}
		e = syscall.Kill(id.PID, syscall.SIGTERM)
	}
	if e != nil && !errors.Is(e, syscall.ESRCH) {
		return e
	}
	for i := 0; i < 50; i++ {
		current, e = processIdentity(id.PID)
		if os.IsNotExist(e) || (e == nil && current != id) {
			return nil
		}
		if e != nil {
			return e
		}
		time.Sleep(100 * time.Millisecond)
	}
	return errors.New("service did not exit")
}

func serviceControl(state, action string) error {
	if action != "stop" && action != "status" {
		return errors.New("unknown service action")
	}
	lock, err := acquireMaintenance(state)
	if err != nil {
		return errors.New("service maintenance or APK installation in progress")
	}
	defer lock.Close()
	id, err := readServiceIdentity(state)
	if os.IsNotExist(err) {
		if action == "status" {
			fmt.Println("stopped")
			return nil
		}
	} else if err != nil {
		return err
	} else {
		if action == "status" {
			fmt.Println("running")
			return nil
		}
		if err = stopIdentity(id); err != nil {
			return err
		}
	}
	for _, name := range []string{"server.pid", "server.identity"} {
		if err = os.Remove(filepath.Join(state, name)); err != nil && !os.IsNotExist(err) {
			return err
		}
	}
	return nil
}

func acquireMaintenance(state string) (*os.File, error) {
	return lockFile(state, "update.lock")
}

func lockFile(state, name string) (*os.File, error) {
	f, err := os.OpenFile(filepath.Join(state, name), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	if err = unix.Flock(int(f.Fd()), unix.LOCK_EX|unix.LOCK_NB); err != nil {
		f.Close()
		return nil, err
	}
	return f, nil
}
func maintenanceActive(state string) bool {
	if state == "" {
		return false
	}
	if _, err := os.Stat(filepath.Join(state, "deployment-recovery")); !os.IsNotExist(err) {
		return true
	}
	f, err := os.OpenFile(filepath.Join(state, "update.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return true
	}
	defer f.Close()
	return unix.Flock(int(f.Fd()), unix.LOCK_SH|unix.LOCK_NB) != nil
}

func waitHealth(addr, want string, attempts int) bool {
	client := &http.Client{Timeout: time.Second, Transport: &http.Transport{Proxy: nil}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	defer client.CloseIdleConnections()
	for i := 0; i < attempts; i++ {
		resp, e := client.Get("http://" + addr + "/healthz")
		if e == nil {
			var data struct{ Status, Version string }
			err := json.NewDecoder(io.LimitReader(resp.Body, 2048)).Decode(&data)
			resp.Body.Close()
			if resp.StatusCode == 200 && err == nil && data.Status == "ok" && data.Version == want {
				return true
			}
		}
		if i+1 < attempts {
			time.Sleep(time.Second)
		}
	}
	return false
}
