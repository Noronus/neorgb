#!/bin/sh
# Build the Arch, Debian and Fedora packages in containers, then install each
# one in a clean container and load the UI once (tests/smoke_gui.py).
#
#   packaging/build-packages.sh [git-ref] [arch|debian|fedora ...]
#
# Needs podman or docker.  Output: dist/
set -eu
cd "$(dirname "$0")/.."
REF=${1:-HEAD}
[ $# -gt 0 ] && shift
DISTROS=${*:-arch debian fedora}
VER=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
SHA=$(git rev-parse "$REF^{commit}")
RT=$(command -v podman || command -v docker)
OUT=$PWD/dist
mkdir -p "$OUT"
git archive --format=tar.gz --prefix="neorgb-$VER/" -o "$OUT/neorgb-$VER.tar.gz" "$SHA"
echo "== Quelle: $REF ($SHA) -> dist/neorgb-$VER.tar.gz"

run() {  # image script
    $RT run --rm -e VER="$VER" -e SHA="$SHA" -v "$OUT:/out" -v "$PWD:/src:ro" "$1" sh -euc "$2"
}

for d in $DISTROS; do
case $d in
arch)
    echo "== Arch"
    run docker.io/library/archlinux:latest '
        pacman -Syu --noconfirm --needed base-devel git python-build python-installer \
            python-setuptools python-wheel pyside6 qt6-svg >/dev/null
        useradd -m b
        mkdir /home/b/pkg
        sed "s|^source=.*|source=(\"neorgb::git+file:///src#commit=$SHA\")|" /src/packaging/arch/PKGBUILD > /home/b/pkg/PKGBUILD
        chown -R b /home/b/pkg
        su b -c "git config --global --add safe.directory \"*\" && cd ~/pkg && makepkg -f --noconfirm"
        cp /home/b/pkg/neorgb-$VER-*-any.pkg.tar.zst /out/
        pacman -U --noconfirm /home/b/pkg/neorgb-$VER-*-any.pkg.tar.zst >/dev/null
        cd / && neorgbctl --help >/dev/null && getent group neorgb >/dev/null && python3 /src/tests/smoke_gui.py'
    ;;
debian)
    echo "== Debian"
    run docker.io/library/debian:13 '
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        apt-get install -y -qq build-essential debhelper dh-python pybuild-plugin-pyproject \
            python3-all python3-setuptools >/dev/null
        mkdir /b && cd /b && tar xf /out/neorgb-$VER.tar.gz && cd neorgb-$VER
        cp -r packaging/debian debian
        dpkg-buildpackage -us -uc -b
        cp ../neorgb_$VER-*_all.deb /out/
        apt-get install -y -qq ../neorgb_$VER-*_all.deb >/dev/null
        cd / && neorgbctl --help >/dev/null && getent group neorgb >/dev/null && python3 /src/tests/smoke_gui.py'
    ;;
fedora)
    echo "== Fedora"
    run registry.fedoraproject.org/fedora:44 '
        dnf -y -q install rpm-build pyproject-rpm-macros python3-devel python3-setuptools \
            python3-wheel python3-pip systemd-rpm-macros >/dev/null
        mkdir -p ~/rpmbuild/SOURCES
        cp /out/neorgb-$VER.tar.gz ~/rpmbuild/SOURCES/
        rpmbuild -bb /src/packaging/fedora/neorgb.spec
        cp ~/rpmbuild/RPMS/noarch/neorgb-$VER-*.noarch.rpm /out/
        dnf -y -q install ~/rpmbuild/RPMS/noarch/neorgb-$VER-*.noarch.rpm >/dev/null
        cd / && neorgbctl --help >/dev/null && getent group neorgb >/dev/null && python3 /src/tests/smoke_gui.py'
    ;;
*) echo "unbekannt: $d" >&2; exit 2 ;;
esac
done
echo "== fertig:"
ls -1 "$OUT"
