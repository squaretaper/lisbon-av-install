# Lisbon Mac mini — headless boot config

The install machine must come fully online after every power cycle with **no monitor, no keyboard, no human present**. If it does not, the operator loses the install.

This document plus `scripts/headless-setup.sh` is the recipe.

## Failure mode observed in space (2026-06-03)

- Mini was unplugged for transport, plugged back in at the install site.
- It booted but never auto-logged-in (login window stuck).
- The venue Wi-Fi password lived in the user's login keychain, which was therefore locked. Wi-Fi never associated.
- Tailscale-over-Ethernet was the only reachable path. Operator (Joshua) had to borrow a monitor and keyboard.

Two independent things were broken: autologin (silently) and the keychain placement of the Wi-Fi password. Fixing one without the other is not enough.

## The four guarantees

A headless mini must satisfy all four:

1. **Tailscale system extension running as root** — gives a remote shell before any login.
2. **Auto-login fully configured** — `autoLoginUser` (name), `autoLoginUserUID` (UID), and `/etc/kcpassword` (obfuscated password blob) all present.
3. **Venue Wi-Fi password in `/Library/Keychains/System.keychain`** — readable by the Wi-Fi daemon pre-login.
4. **Ethernet outranks Wi-Fi in service order** — Wi-Fi is the fallback, not the primary path. Useful when on-site Ethernet exists.

## The script

Run on the mini (locally or via Tailscale SSH) as the install user:

```bash
cd ~/code/lisbon-av-install
INSTALL_USER=ganchitecture VENUE_SSID=Moodscape ./scripts/headless-setup.sh
```

It is idempotent, audits before it changes anything, and prompts for sudo once. It will fail loudly if FileVault is on (autologin is impossible then) or if the SSID has never been joined on this mini.

## After running it

If the script printed `WARN: /etc/kcpassword does not exist`, complete the autologin by opening **System Settings → Users & Groups → Automatically log in as** and re-selecting the user. macOS will write `/etc/kcpassword`. The defaults keys the script set will then take effect on the next boot.

## Verification recipe (the truth test)

Power-cycle the mini with no peripherals attached. From another tailnet node (e.g. `bento`):

```bash
# Tailscale path — should reply within seconds, even before autologin.
tailscale ping ganchi

# SSH path — should work after ~30s once autologin has unlocked the keychain.
ssh ganchitecture@ganchi 'whoami && /usr/sbin/networksetup -getairportnetwork en1'
```

If both succeed, the mini is field-ready. If only Tailscale answers, the autologin/keychain layer is still broken.

## Pitfalls

- **FileVault blocks autologin.** Always off on the install mini.
- **System Settings shows autologin "on" while it is silently broken** when `autoLoginUserUID` is missing. The script checks both.
- **`networksetup -addpreferredwirelessnetworkatindex` saves the password to the login keychain.** Always copy to System keychain afterwards (script handles this).
- **Tailscale CLI is not in `$PATH` when installed from the Mac App Store.** Use `/Applications/Tailscale.app/Contents/MacOS/Tailscale` or `ln -s` to `/usr/local/bin/tailscale`.
- **The keychain copy needs the operator currently logged in** so the login keychain is unlocked. Run the script while you are at the desk, not after walking away.
