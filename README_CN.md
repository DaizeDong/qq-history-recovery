# qq-history-recovery

把你自己的 QQ 聊天记录从腾讯存放它的每一个地方恢复出来,整理成结构化 JSON。这个仓库既是工具,也是一本实战笔记:完整的逆向过程和一路踩过的每一个环境坑都写在 `docs/JOURNEY.md` 里,好让下一个人绕开这些墙。

聊天记录是私有数据,绝不进这个仓库。仓里只有合成 fixture,数据边界闸门强制这一点。代码和文档里出现的每一个账号和密钥都是占位符。

## 三个存储

QQ 把同样的会话存成三种形态,完整度并不相等。

手机端是一个明文 SQLite,消息字段用一个短的重复密钥做 XOR 混淆。最好解,但最不全,因为免费账号只漫游最近约半年。

桌面经典版存 `Msg3.0.db`,消息管理器导出 `.bak`,两者都是腾讯的 SQLCipher 变体,密钥来自运行中的经典客户端。如果只装了 QQNT,这条密钥路走不通,因为 QQNT 不加载经典版的密钥模块。

桌面 QQNT 版存 `nt_qq\nt_db\nt_msg.db`,一个约两 GB、含多年历史的 SQLCipher 库。这才是真正能交付完整历史的档案,也是本仓的主路。

## QQNT 全流程

先取密钥。QQNT 在登录时下发一个 16 字符的 SQLCipher 密钥,只存在内存里。QQBackup 项目的 Windows 取密钥脚本用调试器启动客户端、在密钥函数下断点来读它。**务必先把 QQ 完全退出**,否则脚本启动的实例会被并进已经在跑的那个、断点永远不命中;退干净后再跑脚本,在它弹出的窗口里登录。

然后解密和读取:

```
python tools/qqnt_decrypt.py --in nt_msg.db --out nt_msg_plain.db --key "<16字符密钥>"
python tools/qqnt_decode.py  --db nt_msg_plain.db --out ~/qq-out/qq.jsonl
```

`qqnt_decrypt.py` 处理本仓用证据锁定的格式:1024 字节自定义头,之后是标准 SQLCipher 4 流,盐是偏移 1024 处的 16 字节,参数为 kdf_iter 4000、PBKDF2 HMAC SHA512、页 4096、AES-256-CBC、页 HMAC SHA1。它逐页流式解、校验每一页的 HMAC,绝不写出坏库。`qqnt_decode.py` 读解密后的库,从 protobuf 内容列里取出每条消息的文本,判断谁发的,每条文本消息写一条 JSON。它只往仓外写,因为产物是数据。

## 给消息配上名字

解码出来的消息只用一个形如 `u_SyntheticUid0000000000` 的 QQNT uid 标识对方,人根本读不出那是谁。名字在同一个 `nt_qq\nt_db\` 目录下的兄弟文件 `profile_info.db` 里,格式同样是那层 SQLCipher 包装、密钥也是同一个,所以同一个解密器就能打开。

```
python tools/qqnt_contacts.py --db profile_info.db --key "<16字符密钥>" --out ~/qq-out/contacts.json
```

它写出一份 uid 到名字的纯 JSON 映射:有备注就用机主给这个联系人起的备注,没有就用对方昵称,两者都没有就原样保留 uid,因为解不出来好过安错名字。加 `--friends-only` 只保留已通过的好友。解密出来的临时明文库在提取完就删除,除非加 `--keep-plain`;密钥从命令行或 `$QQNT_KEY` 读取、绝不写进任何文件;映射本身是真实身份数据,和这里其他产物一样只往仓外写。

## 手机端流程

手机端用 `tools/qq_pull.py` 经 adb 拉库,`tools/qq_keyfind.py` 用 frida 16 从运行中的客户端引导出重复 XOR 密钥,`tools/qq_decode.py` 离线解码。让密钥看起来解不出、其实能解的那个「周期陷阱」见 `docs/JOURNEY.md`。

## 导入监控

`tools/qq_import_monitor.py` 在桌面到手机的迁移过程中挂到手机客户端上,记录它的 native 备份库解出了什么。正是靠它我们发现导入只搬文件记录、把文本丢了,也正是靠它找到了桌面库在硬盘上的路径。它只挂钩,绝不强制加载库、也不写客户端。

## 依赖

QQNT 解密器需要 Python 的 `cryptography`;手机端和监控工具需要 `frida==16.7.19`(frida 17 移除了 Java 桥、钩不了安卓客户端)。QQNT 取密钥用的是 QQBackup 项目的 PowerShell 脚本,需要装 QQNT 客户端。离线解密和解析这几步在 QQ 关闭时、对库的副本做,绝不动原文件。

## 数据边界

拉下来的库、解密后的库、解码产物,全是真实运行产物。它们在 `.dataclass.json` 里声明、绝不入库。测试跑在合成 protobuf 消息和 `tools/` 里生成器造的合成手机库上,不需要任何真实数据就能验证代码。
