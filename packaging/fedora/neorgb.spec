Name:           neorgb
Version:        0.1.0
Release:        1%{?dist}
Summary:        RGB lighting and Corsair AIO / fan control for Linux
License:        GPL-3.0-or-later
URL:            https://github.com/Noronus/neorgb
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  python3-setuptools
BuildRequires:  python3-wheel
BuildRequires:  python3-pip
BuildRequires:  systemd-rpm-macros
Requires:       python3-pyside6
Requires:       qt6-qtsvg
Recommends:     openrgb

%description
NeoRGB controls Corsair iCUE Commander CORE (pump, fans, liquid temperature,
RGB) and Lighting Node PRO / CORE directly, with fan curves that are also
stored in the AIO as a fallback. All other RGB devices are driven through a
private OpenRGB server.

%prep
%autosetup -n %{name}-%{version}

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files neorgb
install -Dm644 neorgb/gui/icons/neorgb.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/neorgb.svg
sed 's|@BIN@/||' packaging/neorgb.desktop > neorgb.desktop
install -Dm644 neorgb.desktop %{buildroot}%{_datadir}/applications/neorgb.desktop
sed 's|@BIN@|%{_bindir}|' packaging/neorgbd.service > neorgbd.service
install -Dm644 neorgbd.service %{buildroot}%{_userunitdir}/neorgbd.service
install -Dm644 packaging/60-neorgb.rules %{buildroot}%{_udevrulesdir}/60-neorgb.rules

%check
%{python3} -m unittest tests.test_offline

%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%{_bindir}/neorgb
%{_bindir}/neorgbd
%{_bindir}/neorgbctl
%{_datadir}/applications/neorgb.desktop
%{_datadir}/icons/hicolor/scalable/apps/neorgb.svg
%{_userunitdir}/neorgbd.service
%{_udevrulesdir}/60-neorgb.rules

%changelog
* Sun Nov 08 2026 Noronus <74186111+Noronus@users.noreply.github.com> - 0.1.0-1
- First release
