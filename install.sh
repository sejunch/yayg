#!/usr/bin/env bash
# yayg 설치 스크립트.
#
#   ./install.sh              pacman 패키지로 설치 (권장)
#   ./install.sh --home       홈 디렉터리에 설치 (root 불필요)
#   ./install.sh --uninstall  둘 중 설치된 것을 제거
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
LIB="$DATA/yayg"
BIN="$HOME/.local/bin"
APPS="$DATA/applications"
ICONS="$DATA/icons/hicolor/scalable/apps"
DESKTOP_ID="io.github.sejunch.yayg"
PKGNAME="yayg"

usage() {
    sed -n '2,6p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
    exit 0
}

die() { echo "오류: $*" >&2; exit 1; }

# root 로 돌리면 makepkg 가 거부하고, 홈 설치는 엉뚱한 곳에 깔린다.
[[ $EUID -eq 0 ]] && die "root 로 실행하지 마세요. 필요한 곳에서 sudo 를 물어봅니다."

refresh_caches() {
    command -v update-desktop-database >/dev/null &&
        update-desktop-database -q "$APPS" 2>/dev/null || true
    command -v gtk-update-icon-cache >/dev/null &&
        gtk-update-icon-cache -qtf "$DATA/icons/hicolor" 2>/dev/null || true
}

home_installed() { [[ -e "$BIN/yayg" || -e "$APPS/$DESKTOP_ID.desktop" ]]; }
pkg_installed()  { pacman -Qq "$PKGNAME" >/dev/null 2>&1; }

remove_home() {
    rm -rf "$LIB"
    rm -f "$BIN/yayg" "$APPS/$DESKTOP_ID.desktop" "$ICONS/$DESKTOP_ID.svg"
    refresh_caches
}

# -- 홈 설치 -----------------------------------------------------------------

install_home() {
    command -v python3 >/dev/null || die "python3 가 필요합니다"
    python3 -c 'import gi; gi.require_version("Adw","1")' 2>/dev/null ||
        die "python-gobject, gtk4, libadwaita 가 필요합니다"

    mkdir -p "$LIB" "$BIN" "$APPS" "$ICONS"

    rm -rf "$LIB/yayg"
    cp -r "$SRC/yayg" "$LIB/"
    cp "$SRC/run.py" "$LIB/"
    find "$LIB" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

    cat > "$BIN/yayg" <<SH
#!/usr/bin/env bash
exec python3 "$LIB/run.py" "\$@"
SH
    chmod +x "$BIN/yayg"

    install -Dm644 "$SRC/data/$DESKTOP_ID.svg" "$ICONS/$DESKTOP_ID.svg"

    # 런처는 로그인 셸의 PATH 를 물려받지 않을 수 있으므로 Exec 을 절대 경로로.
    sed "s|^Exec=yayg$|Exec=$BIN/yayg|" "$SRC/data/$DESKTOP_ID.desktop" \
        > "$APPS/$DESKTOP_ID.desktop"
    chmod 644 "$APPS/$DESKTOP_ID.desktop"

    command -v desktop-file-validate >/dev/null &&
        { desktop-file-validate --no-hints "$APPS/$DESKTOP_ID.desktop" ||
          echo "경고: 데스크톱 항목 검증에서 문제가 보고되었습니다" >&2; }

    refresh_caches

    echo "홈 디렉터리에 설치했습니다."
    echo "  실행 파일   $BIN/yayg"
    echo "  런처 항목   $APPS/$DESKTOP_ID.desktop"
    case ":$PATH:" in
        *":$BIN:"*) ;;
        *) echo; echo "경고: $BIN 이 PATH 에 없습니다. 런처로는 실행되지만 터미널에서는 안 됩니다.";;
    esac
}

# -- pacman 패키지 -----------------------------------------------------------

install_package() {
    command -v makepkg >/dev/null || die "makepkg 가 없습니다. sudo pacman -S --needed base-devel"
    [[ -f "$SRC/packaging/$PKGNAME/PKGBUILD" ]] ||
        die "packaging/$PKGNAME/PKGBUILD 를 찾을 수 없습니다"

    if home_installed; then
        echo "홈 디렉터리 설치본이 이미 있습니다."
        echo "그대로 두면 런처에 항목이 두 개 뜹니다. 지금 지울까요? [Y/n] "
        read -r answer
        if [[ -z "$answer" || "$answer" =~ ^[Yy] ]]; then
            remove_home
            echo "  홈 설치본 제거됨"
        else
            echo "  그대로 둡니다 — 런처 항목이 중복될 수 있습니다"
        fi
        echo
    fi

    echo "패키지를 빌드합니다. 설치 단계에서 sudo 비밀번호를 물어봅니다."
    echo "(소스는 PKGBUILD 에 적힌 GitHub 릴리스에서 받아옵니다 — 지금 작업 중인"
    echo " 로컬 수정본이 아니라 태그된 버전이 설치됩니다.)"
    echo
    ( cd "$SRC/packaging/$PKGNAME" && makepkg -si )

    echo
    echo "설치 완료. 앱 런처에서 'yayg' 로 검색하세요."
    echo "제거하려면: sudo pacman -R $PKGNAME"
}

# -- 제거 --------------------------------------------------------------------

uninstall() {
    local done_any=0
    if home_installed; then
        remove_home
        echo "홈 설치본을 제거했습니다."
        done_any=1
    fi
    if pkg_installed; then
        echo "pacman 패키지가 설치되어 있습니다. 제거합니다."
        sudo pacman -R "$PKGNAME"
        done_any=1
    fi
    [[ $done_any -eq 0 ]] && echo "설치된 yayg 를 찾지 못했습니다."
    return 0
}

case "${1:-}" in
    ""|--package|-p) install_package ;;
    --home|-H)       install_home ;;
    --uninstall|-u)  uninstall ;;
    -h|--help)       usage ;;
    *)               die "알 수 없는 옵션: $1  (--help 참고)" ;;
esac
