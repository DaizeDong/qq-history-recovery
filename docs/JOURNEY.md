# Recovering QQ chat history: the whole journey, and every trick that mattered

This is the field notebook for pulling a person's own QQ chat history out of Tencent's storage, across
the mobile client, the desktop client, and the message manager exports. It records what each store
actually is, the cipher on each, and the long list of environment traps that cost real time, so the
next attempt skips them. Every account number in here is the synthetic `123456789`, and every key is a
placeholder. No real identifier appears in this repository.

## The three stores, and why you end up needing the desktop one

QQ keeps the same conversations in three different shapes, and they are not equal.

The mobile client (`com.tencent.mobileqq`, the classic 8.x line, not QQ NT) keeps a plain SQLite file
at `/data/data/com.tencent.mobileqq/databases/<uin>.db`. It is fully readable once you know the field
cipher, but it only holds a roaming window. On a free account that window is about the last six months,
and nothing you do on the phone reaches further back. So the mobile store is the easiest to decode and
the least complete.

The desktop client (classic QQ or TIM on Windows) keeps everything at
`C:\Users\<user>\Documents\Tencent Files\<uin>\Msg3.0.db`, which on a heavy account is hundreds of
megabytes and goes back years. This is the real archive. It is in the harder MSG0 format described
below.

The message manager exports (`<name>(<uin>).bak`) are ZIP files, each containing one MSG0 database per
conversation. They are slices of the desktop store, same format, so cracking one cracks all.

The lesson that took the longest to learn: the phone can never give you the full history, because
roaming does not carry it. If you want everything, you go to the desktop store or its exports, not the
phone.

## The mobile field cipher: a repeating XOR, and the period trap

Invariant: the mobile `<uin>.db` is a normal unencrypted SQLite file. Only the message payload column
`msgData` and the account number columns are obfuscated, by XOR against a short repeating key. Decode
is the same operation as encode.

The one thing that will waste a day is the period. The key on the reference device was fifteen bytes of
ASCII digits. An earlier pass recovered only the first nine of them, because nine bytes is exactly three
Chinese characters in UTF-8, so a nine byte key cleanly decodes the first three characters of every
message and then drifts into garbage. That looked like a per message keystream and sent the whole
analysis down a blind alley. It was simply the wrong period. Recover the key from one long known
plaintext, do not guess it, and confirm the period covers the whole known pair before trusting it.

Recovering the key without guessing: every message the owner sent carries `senderuin` equal to the
owner account number, which is known plaintext, so XOR the stored bytes against the ASCII of the account
number to read the key straight off. That gives the first nine bytes. For the full fifteen, read one
long already decoded message out of the running client's memory (see the Frida section) and XOR it
against its encrypted row, matched by `uniseq`. Table naming is `mr_friend_<uppercase md5 of the friend
uin>_New` for private chats and `mr_troop_<uppercase md5 of the group>_New` for groups; text messages
are `msgtype = -1000`, replies are `-1049`, and the many `-2005` rows are file transfer records with no
text.

## The MSG0 format: the desktop store and the .bak exports

Both `Msg3.0.db` and the databases inside a `.bak` start with the ASCII bytes `SQLite header 3\0`, not
the standard `SQLite format 3\0`, and carry an ASCII `MSG0` marker at offset 0x20 followed by header
metadata. A normal SQLite reader will not open them.

The schema is recoverable and told us the cipher shape. Column names are stored as UTF-16 XORed with a
single key byte, and that key byte is the bitwise complement of a length prefix that sits two bytes
before the string. Concretely, a length byte of 0x1a decodes with key 0xe5 (0xff xor 0x1a) and yields a
column name like `SysLocalHash`, and a length byte of 0x14 decodes with key 0xeb. So the header and
schema come out cleanly.

The message content is harder. The same simple relation does not decode the row payloads deep in the
file, which come out as noise, so the content carries a heavier scheme (a per record key, or a
compression layer under the XOR). This is where a store specific decryptor earns its keep, and where
this repository's decrypt tool picks up. Do not assume the schema trick decodes the messages; it does
not.

## The Frida trick that found the desktop store

The single highest value move in the whole effort was hooking the phone during a desktop to phone
import, because it revealed three things at once.

When you start a migration, the phone client loads its native backup library and decrypts the incoming
stream. Hooking the decrypt entry points showed that the import fetches messages one at a time by a
request like `getmsg?fid=<n>&chatUin=<n>&chatType=<n>`, and that what actually crosses to the phone is
file and image records, not text. That is why an imported history shows only file transfer entries: the
import drops the text on the way in. It is an import limitation, not a display bug.

The same decrypted requests carried the desktop file path, which is how we learned the desktop store
lives at `Documents\Tencent Files\<uin>\Msg3.0.db`. So the phone monitor, which we set up to diagnose a
broken import, is what pointed at the real archive on disk. When a path is fighting you, instrument the
thing that already knows the answer and read the answer out of it.

## Environment traps, each one paid for in time

Frida version. Frida 17 removed the Java and ObjC bridges from the injected agent, so inside an inline
script `Java` is simply undefined even though libart is loaded. Use Frida 16 on both sides. The device
here already shipped a `frida-server-16` binary, and the desktop side is `pip install frida==16.7.19`.
Enumerate and hook through the Frida Python API, since the frida-tools command line pins a newer Frida.

Never spawn on this emulator. Frida spawn on MEmu leaves a frozen process behind that goes into
uninterruptible sleep and poisons `/proc`, after which `ps`, `pidof`, `uiautomator dump`, and even
Frida enumeration all hang. Launch the app the normal way with `am start`, then attach. And attach by
PID, not by name, because attach by name calls process enumeration internally and that is the call that
hangs. Clear a stuck process only by exact PID with `kill -9 <pid>`, which does not walk `/proc`.

Do not reboot to clear a wedge. `adb reboot` on MEmu left the emulator worse, unresponsive to even a
trivial shell echo. You cannot kill or restart the MEmu process without administrator rights, and its
`memuc` control tool needs elevation for every subcommand. The one lever that works without elevation is
launching the player executable directly, which starts the instance, and letting the user close it from
the window when it needs a clean restart.

The emulator shell is already root. Wrapping commands in `su -c` hangs the whole shell on this build, so
run everything through the plain root `adb shell`.

Screenshots are blocked but the view tree is not. `screencap` returns a blank white image on the chat
client because of its secure flag, so you cannot see the screen. `uiautomator dump` still returns the
full view hierarchy with element bounds, so you navigate by dumping the tree and tapping coordinates.
The conversation list is the exception: the client does not expose conversation names to accessibility,
so you cannot read which row is which, only tap them.

Open a specific chat directly. Rather than hunt the unlabeled conversation list, open a known
conversation by uin with an intent to `mqqwpa://im/chat?chat_type=wpa&uin=<uin>&version=1`. This is how
you scroll a specific friend's history without guessing which row they are.

The roaming wall is real. Scrolling a chat does load older messages into both memory and the local
database, and that genuinely grows the owner message count, but only back to the roaming boundary, which
was about six months on this free account. Past that the client fetches nothing no matter how far you
scroll, and there is no load more button to press. The years before that boundary exist only in the
desktop store.

## What this repository ships

The tools here decode each store: the mobile repeating XOR decoder, the Frida key bootstrap that reads
the fifteen byte key out of the running client, the MSG0 decryptor for the desktop store and the .bak
exports, and the import monitor that produced the findings above. Chat history is treated as private
data and never enters this repository. Only synthetic fixtures ship, and a data boundary gate enforces
it.

## The winning path: the desktop QQNT store

The mobile roaming window is too short and the classic desktop Msg3.0.db needs a key that only a
running classic client holds, which was not installed here. The path that actually delivered the full
history was the desktop QQNT store.

Modern QQ on the desktop is QQNT, and it keeps everything in one large encrypted SQLite at
`Documents\Tencent Files\<uin>\nt_qq\nt_db\nt_msg.db`, which on a real account is around two gigabytes.
On the reference machine that one file held about six hundred and thirty thousand group messages and a
hundred and thirty thousand private messages, against the eighty seven the phone could reach. This is
the archive.

Getting the key. QQNT encrypts the store with SQLCipher, and the sixteen character key is issued at
login and lives only in the running client's memory. The QQBackup project's key extractor for Windows
finds the key function inside the client's native module by its debug string, launches the client under
a debugger with a breakpoint on that function, and reads the key out when the client opens the database
at login. The one thing that trips this up: the desktop client is single instance, so if a normal
logged in client is already running, the extractor's freshly launched instance just merges into it and
the breakpoint never fires. Quit the client completely first, then run the extractor, then log in to
the window it opens. The breakpoint fires on that login and prints the key.

The file format, pinned by evidence not by guessing. The first sixteen bytes are the ASCII marker
`SQLite header 3\0`, and at offset 0x20 there is a `QQ_NT DB` marker with a little header metadata and
a hex blob. From 0x100 to 0x3FF the file is zeros, and at offset 0x400, exactly 1024 bytes in, the
entropy jumps and the real SQLCipher stream begins. So the layout is a 1024 byte custom header followed
by a standard SQLCipher 4 database, and the SQLCipher salt is the sixteen bytes at offset 1024, not the
visible header. The parameters are kdf_iter 4000, PBKDF2 HMAC SHA512 key derivation, page size 4096,
AES-256-CBC per page with the IV stored in a 48 byte reserved region at each page end, and page
authentication by HMAC SHA1. The way to be sure these are right is to require the page 1 HMAC to
verify. It did, on all but one free page out of four hundred and eighty thousand, and the decrypted
page 1 began with a valid `SQLite format 3` header. tools/qqnt_decrypt.py streams the decryption page by
page with that verification so it never emits a corrupt database.

Reading the messages. The decrypted database has numeric column names and stores each message body as
a protobuf in column 40800. Sender is a uid string in column 40020, the peer uin or group number is in
40030, and the time is in 40050. The owner's uid is simply the sender that appears across the most
private conversations. Inside the protobuf the text of a text element sits in field 45101, and a reply
keeps the quoted original under field 47423, which is skipped so a reply does not re-import the message
it answers. tools/qqnt_decode.py does exactly this and writes one record per text message. On the
reference store it recovered around forty eight thousand of the owner's own text messages, next to the
eighty seven the phone had.

One more trap worth stating plainly: the desktop machine may be running QQNT while an older classic
Msg3.0.db also sits on disk. They are different formats with different keys. The classic Msg3.0.db is
also a 1024 byte header over an encrypted store, but its key comes from a running classic client and
its native `KernelUtil.dll`, which QQNT does not load, so the QQNT key does not open it. Decide which
store you are holding from the process that is actually running, and do not mix the two key routes.

## The names were never missing: profile_info.db

The decoded messages come out identified only by a QQNT uid, a string like `u_SyntheticUid0000000000`. That is useless to a person reading their own history, because you cannot tell who it is. The natural reading of that is that the names simply were not exported, that the message store is a bag of text with the identities stripped, and that recovering them means some second route entirely: scraping the client UI, or asking the server. All of that is wasted work. The names are one file over, in `profile_info.db`, sitting in the same `nt_qq\nt_db\` directory as `nt_msg.db`, and that file is the same Tencent wrapped SQLCipher 4 format with the same 1024 byte custom header, the same salt position, the same kdf_iter 4000, and the same 16 character client key. `tools/qqnt_decrypt.py` opens it with no changes at all. The trap is not a hard format, it is an assumption: when one file in a store hands you opaque ids, look at its siblings before you conclude the mapping is gone, because a store that keeps ids almost always keeps the table those ids point into.

The contact table is `profile_info_v6`, and like the message tables it uses numeric column names, so nothing tells you which column is which. The way to tell them apart is not to read them, it is to count them. On the reference store the table had 23263 rows, and three columns carried strings worth looking at. Column `1000` is the uid: it is present on every row, it is unique, and its values are exactly the `u_` prefixed strings that appear as the sender in the decoded messages, which is the join proving it is the key. Column `20002` is populated on almost every row with a median length of 4 characters, and a value that short and that universal is a nickname, not prose. Column `20009` is populated on only a couple of hundred rows out of the 23263, which is the shape of a field only real friends have, and it is the owner's private remark for that contact. Column `20011` is populated widely with a median length of 13 and a longest value over 100 characters, and that length distribution is prose, not a name: it is the contact's signature line. Value counts and median lengths were enough to separate all four without a single label. There is also a `buddy_list` table, a few hundred rows, keyed by the same uid in column `1000`, which is the accepted friend list if you want the mapping restricted to friends.

Name resolution order is remark, then nickname, then the raw uid. The remark wins because it is the name the owner themselves chose for that person, and it is the one they will actually recognize. The uid has to survive the fallback rather than being replaced by anything cleverer, because there is no honest guess available: putting the wrong person's name over a conversation is a worse outcome than an unresolved id, and an unresolved id at least tells the reader that the tool did not know. `tools/qqnt_contacts.py` does exactly this, shelling out to the existing decryptor rather than carrying a second copy of the decryption, deleting the decrypted plaintext copy afterwards unless asked to keep it, and writing the mapping outside this repository because a list of a person's contacts and what they call them is about as private as the messages themselves.
