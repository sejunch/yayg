# AUR 패키징

AUR 은 소스를 호스팅하지 않는다. `PKGBUILD` 와 `.SRCINFO` 만 올라가고,
소스는 여기 적힌 `source=` 주소에서 받아 간다.

| | 소스 | 용도 |
|---|---|---|
| `yayg/` | GitHub 릴리스 tarball (`v$pkgver`) | 안정판 |
| `yayg-git/` | `git+https://github.com/sejunch/yayg.git` | 최신 커밋 |

## 새 버전을 낼 때

```bash
# 1. 버전 올리고 태그
#    yayg/__init__.py 의 __version__ 과 window.py 의 AboutDialog version 도 함께
git tag -a v0.2.0 -m "yayg 0.2.0" && git push origin v0.2.0

# 2. PKGBUILD 갱신
cd packaging/yayg
sed -i 's/^pkgver=.*/pkgver=0.2.0/; s/^pkgrel=.*/pkgrel=1/' PKGBUILD
updpkgsums                       # sha256sums 재계산
makepkg --printsrcinfo > .SRCINFO

# 3. 빌드 검증 (설치는 하지 않음)
makepkg -f && namcap ./*.pkg.tar.zst
```

`yayg-git` 은 `pkgver()` 가 태그에서 버전을 만들어내므로 보통 손댈 필요가 없다.
`package()` 를 고쳤을 때만 두 쪽에 함께 반영하면 된다.

## AUR 에 올리기

처음 한 번만:

1. https://aur.archlinux.org 계정 생성
2. My Account → SSH Public Key 에 `~/.ssh/id_ed25519.pub` 등록
3. `ssh aur@aur.archlinux.org help` 로 확인 (git 명령 목록이 나오면 성공)

그다음:

```bash
git clone ssh://aur@aur.archlinux.org/yayg.git aur-yayg
cp packaging/yayg/{PKGBUILD,.SRCINFO} aur-yayg/
cd aur-yayg && git add PKGBUILD .SRCINFO && git commit -m "0.1.0-1" && git push
```

AUR 저장소에는 **`PKGBUILD` 와 `.SRCINFO` 만** 커밋한다. 빌드 산출물(`src/`,
`pkg/`, `*.pkg.tar.zst`)은 절대 올리지 않는다.
