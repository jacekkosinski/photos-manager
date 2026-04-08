# NAS APT Repository Setup

Install photos-manager-cli on a Debian-based NAS with automatic updates.

## Prerequisites

- Debian-based system (Debian 13+, Raspbian, Ubuntu 24.04+)
- Architecture: amd64
- Python 3.12+ installed (`python3 --version`)

## Add the APT Repository

```bash
# Import the GPG signing key
curl -fsSL https://jacekkosinski.github.io/photos-manager/gpg.key \
  | sudo gpg --dearmor -o /etc/apt/keyrings/photos-manager.gpg

# Add APT source
echo "deb [signed-by=/etc/apt/keyrings/photos-manager.gpg] \
  https://jacekkosinski.github.io/photos-manager stable main" \
  | sudo tee /etc/apt/sources.list.d/photos-manager.list

# Install
sudo apt update
sudo apt install photos-manager-cli
```

## Verify Installation

```bash
photos --version
photos info --help
```

## Updates

Updates are delivered automatically through apt:

```bash
sudo apt update && sudo apt upgrade
```

## Manual Installation (Alternative)

Download the `.deb` file from
[GitHub Releases](https://github.com/softflow-tech/photos-manager/releases) and
install manually:

```bash
sudo dpkg -i photos-manager-cli_*.deb
sudo apt-get install -f   # install missing dependencies
```

## Troubleshooting

**GPG key error:**

```bash
# Re-import the key
sudo rm /etc/apt/keyrings/photos-manager.gpg
curl -fsSL https://jacekkosinski.github.io/photos-manager/gpg.key \
  | sudo gpg --dearmor -o /etc/apt/keyrings/photos-manager.gpg
```

**Python version too old:** The package requires Python 3.12+. Check your
version with `python3 --version`. On older Debian/Ubuntu, install from backports
or deadsnakes PPA.

**Command not found after install:** The `photos` command should be at
`/usr/bin/photos`. If missing:

```bash
sudo dpkg -L photos-manager-cli | grep bin
```
