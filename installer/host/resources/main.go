package main

import (
	"github.com/tc-hib/winres"
	"os"
)

func main() {
	file, err := os.Open("../assets/app.ico")
	if err != nil {
		panic(err)
	}
	icon, err := winres.LoadICO(file)
	file.Close()
	if err != nil {
		panic(err)
	}
	var rs winres.ResourceSet
	if err = rs.SetIcon(winres.RT_ICON, icon); err != nil {
		panic(err)
	}
	manifest, err := winres.AppManifestFromXML([]byte("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><assembly xmlns=\"urn:schemas-microsoft-com:asm.v1\" manifestVersion=\"1.0\"><assemblyIdentity version=\"1.0.0.0\" processorArchitecture=\"*\" name=\"AndroidWebDesktop\" type=\"win32\"/><trustInfo xmlns=\"urn:schemas-microsoft-com:asm.v3\"><security><requestedPrivileges><requestedExecutionLevel level=\"asInvoker\" uiAccess=\"false\"/></requestedPrivileges></security></trustInfo><application xmlns=\"urn:schemas-microsoft-com:asm.v3\"><windowsSettings><dpiAwareness xmlns=\"http://schemas.microsoft.com/SMI/2016/WindowsSettings\">PerMonitorV2</dpiAwareness><longPathAware xmlns=\"http://schemas.microsoft.com/SMI/2016/WindowsSettings\">true</longPathAware></windowsSettings></application></assembly>"))
	if err != nil {
		panic(err)
	}
	rs.SetManifest(manifest)
	out, err := os.Create("app-res.syso")
	if err != nil {
		panic(err)
	}
	defer out.Close()
	if err = rs.WriteObject(out, winres.ArchAMD64); err != nil {
		panic(err)
	}
}
