# SDK1 → SDK2 轨迹归档迁移交付说明

## 交付文件

| 文件 | 角色 |
| --- | --- |
| `covering.py` | 新增。周期经度 → 平面表示的唯一约定方：折叠、变更线切分、查询框平移。不导入任何 SDK。 |
| `migration.py` | 新增。`upgrade(path, checkpoint=None)` 原子迁移；另含测试用 `upgrade_connection(conn)`。 |
| `reference.py` | 新增。独立周期参照判定器，直接按契约几何用 Fraction 实现，不调用 SDK1 也不调用目标表示转换。 |
| `boundary_tests.py` | 新增。边界/索引/迁移回归与 1800 组随机差分（独立参照 + SDK1 行为 oracle）。 |
| `archive.py` | 改造。同一 `Store` 双 schema：v1 旧路径逐字保留；v2 只读写 SDK2 目标表与 `meta`。 |
| `region.py` | 改造。v2 检索只经 `plane2.candidates` RTree 候选 + `plane2.intersects` 精判；v1 仍走 SDK1。 |
| `upgrade_probe.py` | 仅在入口聚合新回归（旧断言全部保留），探针逻辑本身未改。 |
| `.pointwise-runtime.json` | verify/demo 切到 `upgrade_probe.py`。 |
| `vendor/*`、`fixtures.py`、`model.py` | 未修改。 |

## 1. 平面表示不变量（迁移、兼容 put、原生续写、检索共用）

1. 原始坐标永不重写：`sdk2_tracks.original_json` 保存业务收到的整数点列原文；`get` 返回其全新解析副本。
2. 每条相邻点对先按**原始经度差**折叠成最短有向弧，规则与 SDK1 的 `dx` 折叠逐字一致：`dx>D` 减一个周期、`dx<-D` 加一个周期；恰为 ±D 的平局不位移，方向沿用原始经度差符号；-180° 与 +180° 原始差为 ±周期，折叠为 0，退化为同一经线上的退化线段。
3. 折叠弧若越过基底带 `[-D,D]` 的变更线边界，就在该边界处切成两段，并从对侧等价经线（∓D）按行进方向续写，切点纬度线性插值（整数入参下为整数，必要时以 Fraction 精确保存）。因此：
   - 任何片段坐标都在 `[-D,D]×[-Y,Y]` 内，天然满足 plane2 的 ±3D 限制，与轨迹长度、折返次数无关；
   - 两段在 ±D 等价经线处相接，周期轨迹连续，弧的并集与原周期弧完全相同；
   - 不会出现横跨查询框竖直边界、且交点落在框纬度区间之外的长片段。
4. 查询窗口翻译成通用覆盖面上的闭合平面框：全球窗口（w=-D,e=D）为单个 `[-3D,3D]` 框；其余窗口按真实圆周宽度（`w>e` 的跨线窗口显式加一个周期，不使用 Python 裸取模）生成 k=-1,0,1 三个周期平移框。局部窗口绝不会用全球框取全部候选。

## 2. 归档—检索联动

- 迁移、兼容 `Store.put`、`plane2.native_put` 三条写入路径都向同一套 `sdk2_tracks/sdk2_piece/sdk2_box` 写入同一表示；`plane2.replace` 在调用方事务内自动清除旧片段及其 RTree 行，兼容层不重写该能力。
- 检索只调用 `plane2.candidates`（RTree 保守候选，允许包络误报与重复 ID），再逐片段 `plane2.intersects` 精判，集合去重后排序返回；不扫描 `original_json`，不另建周期几何存储，不调用 SDK1。
- 请求账以**原始坐标**序列化的 payload 为准（与片段无关）：同请求同原文重放返回原回执且不触碰几何，已被后续请求替换的轨迹不会被旧重放恢复；同号异内容抛 `ValueError`，整次 put 在单事务内回滚。代次在 `meta.generation` 全库递增，原生续写与兼容 put 共用同一计数器。
- 切换后旧三表仅作审计，业务读写不再触及；已构造的 `Store` 通过每次操作读取 `meta.schema_version` 即时观察切换。

## 3. 迁移提交边界

- `upgrade` 打开独立连接后 `BEGIN IMMEDIATE`，在同一事务内安装 SDK2 DDL、迁入全部当前轨迹（经 `plane2.replace` 建片段与 RTree）、把 `receipts_v1` 全量逐字搬入 `sdk2_receipts`（历史请求不会变成当前轨迹），最后才把 `meta.schema_version` 置 2。
- 所有目标数据就绪、schema 标记翻转之后、最终 `commit` 之前调用 `checkpoint("before_commit")`；回调异常或任何异常都回滚并原样传播，不捕获进程终止。未提交时被杀死的进程由 SQLite 在重开时丢弃 journal/WAL，旧库内容与 schema 不变，可直接重试。
- 已为 schema 2 的库直接返回（幂等），重复升级无副作用；旧表逐字保留（含 `region_v1_south` 索引）。

## 4. 实际验证结果

- `python3 checks.py`：5 个旧业务/平面 SDK 断言全部通过，旧断言未删除或弱化。
- `python3 boundary_tests.py`：16 个用例通过，含 180° 两方向平局、±180° 等价、折返、多段重复命中、非整数 Fraction 边界交点、全球框、退化点/经线框、排序去重、RTree 查询计划（`VIRTUAL TABLE INDEX`）、选择性窗口不取全部片段、局部窗口不出现全球框、重放不恢复、原生续写立即可见、重复升级与审计表保留。
- 差分：1000 组随机窗口对独立参照 `reference.py`、800 组整数窗口对冻结 SDK1 oracle，结果逐 ID 一致。
- `python3 upgrade_probe.py`：21 个测试 + 注入异常回滚（库镜像逐字不变）+ 真实子进程 SIGKILL 后重试 + 重复升级，输出 `MIGRATION_PROBE_OK`；`demo` 输出真实迁移后行集（schema=2、8 条审计轨迹、替换与原生续写回执）。
- 额外手工核验：失败后字节级镜像一致、冲突 put 后代次/台账不变、替换后无 RTree 孤儿片段、静态确认 v2 生产路径不导入 SDK1。
