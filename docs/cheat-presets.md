# 内置数据预设

两作菜单提供“加载本版本常用预设”，不下载资源，也不写入游戏代码。每次加载全部关闭；必须完整64位十六进制 NSO BuildID 一致（包括相同前缀、不同后缀的错误版本也拒绝）。

BOTW 1.6.0：无限生命、无限体力、卢比设为999999。TOTK 1.4.3：月步（按住游戏跳跃键）。这些是可执行的数据/指针链预设，不是界面占位。只写已验证范围内的main可写区/BSS与当前heap；空/坏指针、安全范围或读写失败自动停用，进入可用场景后可重新启用。全帧预算和只读/宿主内存保护不变。

体力的64位写入允许非8字节对齐：使用Linux内核按字节拷贝，范围与映射校验保留，不使用未对齐的C指针解引用。跨页写入会在触碰内存前拒绝，避免内核短写造成半个值改变；真实只读第二页的回归确认两页原值均不变。界面区分启用、条件等待、写入、立即读回一致、写后再次变化、故障停用。

数据地址与指针关系来源：
- BOTW: https://github.com/WerWolv/EdiZon_CheatsConfigsAndScripts/blob/master/Cheats/01007EF00011E000/cheats/8e9978d50bdd20b4.txt ，公开贡献者 optantic, WerWolv, Grattler, WilHiteWarrior, Testerr。
- TOTK: https://github.com/Arch9SK7/MyNXCheats/blob/main/The%20Legend%20Of%20Zelda%20Tears%20Of%20The%20Kingdom/0100F2C0115B6000/cheats/277178B7DBA1B6D4.txt ，只采用月步数据链，不使用可执行代码补丁、恢复代码或不相关项目。

实现采用公开的版本地址事实、原创有界定义和验证，不打包游戏指令或完整外部集合。静态证据：本人当前包NSO头的完整BuildID与data+BSS范围已核对；回归使用等偏移合成main内存与真实heap，执行生产导入和VM，核验实际字节、未对齐64位写入、按钮条件和真实读回计数。这些测试不等于真实游戏验收，hardware_validated=false，实际玩法由玩家测试。修改过的数据或存档可能保留，全部关闭只停止后续写入。

来源精确提交与内容摘要：
```json
{
  "totk": {
    "repository": "Arch9SK7/MyNXCheats",
    "commit": "04090eb3f6d9d7297672d53628766fd60c591d48",
    "path": "The Legend Of Zelda Tears Of The Kingdom/0100F2C0115B6000/cheats/277178B7DBA1B6D4.txt",
    "sha256": "fb9216dff9f3bc386189cb9258f69ec57b6b758b206c5feae438a89ab0aaf386"
  },
  "botw": {
    "repository": "WerWolv/EdiZon_CheatsConfigsAndScripts",
    "commit": "d16d36c7509c01dca770f402babd83ff2e9ae6e7",
    "path": "Cheats/01007EF00011E000/cheats/8e9978d50bdd20b4.txt",
    "sha256": "830f1374994a397080029f1e6ba1ee8b964ae51a13bca77641d5ae1015497ae8"
  }
}
```
