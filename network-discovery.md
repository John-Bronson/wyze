# Finding the Pi on the Local Network

How the Raspberry Pi running this project was located on 2026-09-07, after its
address was forgotten. The short version: **ask the network what it is, before
scanning it for what it might be.**

## Why not netstat?

`netstat` (and its modern replacement `ss`) is a **host-local** tool. It answers
"what is *this* machine listening on, and who is *this* machine talking to?" It
has no way to enumerate other devices — a Pi sitting quietly on your LAN never
appears in `netstat` output unless you already have a connection open to it.

The two useful exceptions are indirect:

```bash
netstat -rn          # routing table - tells you your subnet and gateway
arp -a               # ARP cache - hosts THIS machine has recently talked to
ip neigh             # same thing, modern syntax
```

The ARP cache is worth a look because it is free, but it only contains hosts
you have contacted recently, so a Pi you have ignored for a year won't be there.

## Step 0: know your own subnet

Everything downstream needs this.

```bash
ip -br addr                 # your addresses, one line per interface
ip route | grep default     # your gateway
```

In this case:

```
enp191s0   UP   10.28.1.174/24
default via 10.28.1.1 dev enp191s0
```

So the network is `10.28.1.0/24` — addresses `10.28.1.1` through `10.28.1.254`.
The `/24` matters: it is the search space for any scan.

## Step 1: mDNS — ask, don't scan

This is the step that actually found the Pi, and it is the one most people skip.

**mDNS** (multicast DNS, also called Bonjour or zeroconf) lets devices announce
themselves and their services on the local link. Raspberry Pi OS runs
`avahi-daemon` by default, so **a Pi is broadcasting its own name and services
without being asked**. You just have to listen.

```bash
# Resolve a guessed name directly
avahi-resolve -4 -n rpi-zero.local
avahi-resolve -4 -n raspberrypi.local        # the factory default name

# Reverse: what name owns this address?
avahi-resolve -4 -a 10.28.1.125
```

Be aware the reverse direction is the weaker one. On this network it answers
`rpi-zero.attlocal.net` — the name the *router's* DNS holds, not the mDNS
`.local` name — because the resolver falls back to unicast DNS. Treat a reverse
result as a hint; the forward lookup and `avahi-browse` are the reliable half.

If you do not know the name, **browse for it**. Every Pi advertises a
`_workstation._tcp` record:

```bash
avahi-browse -tp _workstation._tcp
```

which is what produced the answer here:

```
+;enp191s0;IPv4;rpi-zero\032\0912c\058cf\05867\058e8\05896\05835\093;Workstation;local
```

The mangled text is escaped — `\032` is a space and `\058` a colon, so that
decodes to `rpi-zero [2c:cf:67:e8:96:35]`, name plus MAC address.

Browse for a specific service instead when you care about capability rather
than identity — `-r` resolves each hit to an address and port:

```bash
avahi-browse -rtp _ssh._tcp        # everything advertising SSH
avahi-browse -rtp _http._tcp       # everything advertising a web server
avahi-browse -atp                  # every service type on the network
```

Flags used above: `-t` terminate after the initial sweep instead of watching
forever, `-p` parseable output, `-r` resolve to host/address/port, `-a` all
service types.

If `nss-mdns` is installed, ordinary tools resolve `.local` names too, no
special client needed:

```bash
getent hosts rpi-zero.local
ping -c1 rpi-zero.local
ssh bronson@rpi-zero.local
```

**Limits of mDNS.** It is link-local multicast: it does not cross subnets or
VLANs, many routers block it between wired and wireless segments or in "guest"
and "AP isolation" modes, and the device must actually be running `avahi-daemon`
(Raspberry Pi OS Lite does, but a stripped image may not).

## Step 2: port scan, to confirm and to fill gaps

Scanning is the fallback for when mDNS is blocked or the device is silent. Here
it served as confirmation and to see what else was around.

```bash
nmap -p22 --open -T4 -n 10.28.1.0/24
```

| flag | meaning |
|---|---|
| `-p22` | check only port 22 — one port across 254 hosts is fast |
| `--open` | list only hosts where the port is open; suppresses the noise |
| `-n` | **no reverse DNS** — the single biggest speedup |
| `-T4` | aggressive timing; fine on a LAN you own |

Result — four SSH servers:

```
10.28.1.125    10.28.1.146    10.28.1.175    10.28.1.180
```

Scan several ports at once when you are hunting for a service rather than a
host, and drop `--open` if you want to see filtered ports too:

```bash
nmap -p22,80,443,5000 --open -T4 -n 10.28.1.0/24
nmap -sn 10.28.1.0/24        # ping sweep: who is alive, no port scan
```

`nmap -sn` is the quickest "what is on this network at all" question, and
`sudo nmap -sn` additionally reports MAC addresses and vendor names — a
Raspberry Pi Foundation OUI is a strong hint on its own.

Only scan networks you own or are authorized to test.

## Step 3: tell the hosts apart

Four open SSH ports, and no indication which was the Pi. **Banner grabbing**
settles it — an SSH server announces its software and OS before authentication:

```bash
nc -w 3 10.28.1.125 22 </dev/null | head -1
```

```
10.28.1.125   SSH-2.0-OpenSSH_9.2p1 Debian-2+deb12u7      <- Pi (Debian 12)
10.28.1.146   SSH-2.0-OpenSSH_9.3
10.28.1.175   SSH-2.0-OpenSSH_8.4p1 Raspbian-5+deb11u7    <- literally says Raspbian
10.28.1.180   SSH-2.0-OpenSSH_10.0p2 Debian-7
```

`nmap -sV -p22 <ip>` does the same thing with more parsing, and `ssh-keyscan`
fetches host keys, useful for matching a host against your `known_hosts`.

Then identify the *application*, not just the OS, by asking the web server:

```bash
curl -s -i -m 5 http://10.28.1.125/
```

The Pi returned the Flask app's own error page — conclusive. The other machine
returned a Pi-hole admin page. Two Raspberry Pis, told apart in one command.

## Step 4: checking your own history

Hashed `known_hosts` entries cannot be read directly, but they can be *tested*
against a candidate name or address:

```bash
ssh-keygen -F rpi-zero.local -f ~/.ssh/known_hosts
ssh-keygen -F 10.28.1.125    -f ~/.ssh/known_hosts
```

A match means you have connected before. Also worth grepping:

```bash
grep -iE 'ssh|scp|rsync' ~/.bash_history | tail -40
cat ~/.ssh/config
```

## The order that works

1. `ip -br addr` — establish the subnet
2. `avahi-browse -tp _workstation._tcp` — let the Pi introduce itself
3. `avahi-resolve -4 -n <name>.local` — turn its name into an address
4. `nmap -p22 --open -T4 -n <subnet>` — fall back to scanning if mDNS is quiet
5. `nc <ip> 22` — read SSH banners to tell candidates apart
6. `curl -s -i http://<ip>/` — confirm by the application it serves

Steps 2 and 3 took under a second and produced the answer. Steps 4 through 6
are what you need when mDNS is blocked, the device is headless and silent, or
several similar machines are on the same wire.

## If none of it works

- **Check the router's DHCP lease table.** It is authoritative — every device
  that got an address is listed, usually with hostname and MAC.
- **`sudo arp-scan --localnet`** actively ARPs the whole subnet and prints MAC
  vendors. It finds hosts that ignore pings and advertise nothing.
- **Look up the MAC prefix.** Raspberry Pi OUIs include `b8:27:eb`, `dc:a6:32`,
  `e4:5f:01`, and `2c:cf:67` (this Pi).
- **Serial console or a monitor** — when the Pi never joined the network at all,
  no amount of scanning will conjure it.

## Making this unnecessary next time

The reason this hunt was needed is that the address was never written down.
Fixes, cheapest first:

```bash
# 1. Use the mDNS name everywhere instead of an IP - survives DHCP changes
ssh bronson@rpi-zero.local

# 2. Give it a stable alias in ~/.ssh/config
Host rpi-zero
  HostName rpi-zero.local
  User bronson
  IdentityFile ~/.ssh/rpi_zero

# 3. Reserve its address in the router (DHCP static lease), keyed to its MAC
```

This project now uses option 2 — see `deploy.sh`, which refers to the host only
as `rpi-zero` and never hardcodes an address.
