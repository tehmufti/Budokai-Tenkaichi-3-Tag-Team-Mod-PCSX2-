TAG TEAM MOD - ONLINE 2.2 (protocol 7)
=======================================

Install the same Tag Team Mod release on every PC, then run Play online.cmd
(Linux: Play online.sh). The selected disc, BIOS and PCSX2 come from the
installation. Online uses its own emulator profile and settings in online/data;
your offline settings, saves and memory cards are not changed. Upgrading imports
your online profile. Room passwords are not saved.

SUPPORTED DISCS
BT3 USA, BT3 Europe, BT3 Japan (Sparking! Meteor), and the reviewed BT4 B14 REV2
English and Spanish discs. Everyone in a room must use the SAME disc contents,
adapter and release. This is regional support, not cross-region or BT3/BT4
cross-play. The handshake checks game resources, patches, code and emulation
settings before a match starts. Unknown executable variants still require a
reviewed adapter. Use Mod settings > Game disc to select an installed disc,
then close and reopen Play online.

HOST AND JOIN
One PC hosts. The others click Join a room, then enter its address in the
dialog (IP or hostname, optionally followed by :port).
Everyone enters as a spectator. Claim any fighter, then press Ready. Unclaimed
fighters are CPU. The host selects characters, costumes, stage, music and rules
and starts after the players are ready. Each PC shows its own fighter's view.
Either team may have one to five fighters, independently (2v1, 5v3, etc.), with
at most ten fighters and ten human players. Free-for-all supports 2-10 fighters.
A room holds up to sixteen members, including spectators. A departing player's
fighter becomes a CPU, so the match can continue.

In the host's room rules, "If a player fails to load" defaults to "Cancel the
start". "Drop and continue" removes a player whose load fails, or who has not
loaded after 120 seconds, and gives their fighter to a CPU. The remaining
players must still finish loading before the intros begin together. Spectators
do not delay the start. The removed player can join again as a spectator.
The option is saved for the host's next room. Losing the host, or a failure to
load the host's game, always stops the start/session; it cannot migrate hosts.

Host rules, including camera/cinematic rules, apply to everyone. My display
changes only cosmetic preferences on your PC. Expanded maps and widescreen are
disabled online. Body Change and timed fusion are not supported online yet.
CPU transformations are optional; extra resource changes briefly hold the match
at an agreed frame so all PCs replace the model together.

MATCH ROOM AND HANGOUT
The match room is the window where you choose characters, teams and rules.
After a match, Retry requires the players to agree within ten seconds. Return
to lobby returns to this CHARACTER-SELECTION ROOM; it does not launch a hangout.

Start in: Hub launches the playable hangout. Fight freely opts into combat;
otherwise hitting back gives mutual consent, and if you die you just respawn. Challenge
can request a duel in that map or a full match. Accepting a full-match challenge
opens character selection, with the challengers seated and everyone else watching.
After that match you can rematch or change characters in this room. The host's
Back to hangout button returns the room to its saved hub and restores scores.
There is ONE active match per room: challenges currently move the whole room;
they do not create an independent match while other people keep roaming.

Unequal teams use the online result screen immediately at the native K.O.
The native victory presentation is skipped because its padded roster could
deadlock the game's renderer. The winner and final sync check are preserved.

JOINING AND PASSWORDS
Click Join a room to enter the host address. Recent hosts are offered in the
dialog. Cancel returns to the start screen without connecting. Addresses with
missing hosts or invalid port numbers are rejected before connecting.

For a private room, the host can set an optional Room password under Advanced;
the guest enters it in the Join dialog. Passwords are not saved in the profile
or logs. Server-browser, room-listing and directory controls are hidden for now;
rooms opened from the player window are not advertised. Join by address.

CONNECTIVITY AND TROUBLESHOOTING
Allow Python through the firewall. For direct internet hosting, forward the
chosen game port (default 47400), BOTH TCP and UDP, or use a VPN such as Tailscale,
ZeroTier or Radmin VPN. TCP carries rooms/checkpoints; UDP carries frame inputs.
A directory listing alone does not make a host reachable through NAT.

TTM-NET-01/02: install the same release on all PCs. TTM-NET-06: use identical
disc contents. TTM-NET-17: correct the room password or the indicated rule.
TTM-NET-10/11: check address, firewall and both port protocols. TTM-NET-23/31:
retry preparation; if it repeats, preserve the run report. A desync is reported
and repaired from the host's checkpoint; repeated failures stop the match.
Do not load emulator savestates or use the native pause/result menus online.
Logs and reports are in online/runs. They can include selected paths, display
names and network endpoints; review them before sharing. BIOS and disc files
are not included in the release or uploaded to a directory.

VALIDATION LIMITS
This remains a beta. Local multi-instance matches and simulated network loss
are useful checks, but do not certify separate PCs, real internet connections,
every move/stage/controller, or Linux gameplay. Choose a public test accordingly.
PCSX2 is distributed under its own license; see licenses in the installation.
