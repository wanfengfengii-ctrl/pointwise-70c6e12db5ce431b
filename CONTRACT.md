# 轨迹归档的公开契约

这是一份可运行的旧工程，不是已实现的迁移。archive.py 负责轨迹原文、替换和请求账；region.py 负责区域候选、精确相交及原轨迹身份。fixtures.py 的独立 SQL 是冻结旧库，既不调用 Store，也不调用任一 SDK。vendor/periodic1.py 与 vendor/plane2.py 是项目自有的完整离线依赖，不代表第三方产品。SDK2不含周期转换或迁移实现，migration.py 应由本次交付新增。

## 已有调用和格式
Store(path) 接受 SQLite 文件路径，也接受 isolation_level=None 的 sqlite3.Connection；构造空库时建旧版表。Store.conn 是现有公开连接，close() 关闭它。数据入口为 put(request_id,track_id,points)、get(track_id)、search(west,south,east,north)，无需服务器。
request_id、track_id 是非空字符串；points 是至少两个坐标对的列表或元组，坐标为非布尔整数，单位百万分之一度；经度范围 [-180000000,180000000]，纬度范围 [-90000000,90000000]。返回或保存时规范为列表。
put 同轨迹ID替换；返回 {"request_id":请求号,"track_id":轨迹号,"revision":全库递增代次}。同请求号同原始内容重放返回原回执，绝不把已被后续请求替换的旧轨迹恢复；同号异内容抛 ValueError 且不改库。等价经度写法仍是不同原始内容。get 返回原始坐标列表，不存在返回 None；外部修改返回列表不影响存储。所有验证失败抛 ValueError，整次 put 不改变任何持久状态。

相邻点按最短经度弧连接，恰为180°时沿原始经度差的符号；-180°与180°为同一经线。轨迹是各相邻线段的并集，纬度沿该线段线性插值，不作球面测地计算。重复点及退化线段合法。
search 的四参数与坐标使用相同整数单位，south<=north；非法窗口抛 ValueError。窗口闭合，边、角、单点接触均算相交；返回排序去重的轨迹ID列表。west>east表示跨线区域，west=-180°且east=180°表示全球经度范围，其余相等经度表示单条经线；west=180°、east=-180°也只表示日期变更线。同坐标不同ID仍分别返回。无匹配返回 []。

## 冻结旧库
完整 DDL 和全部数据原文在 fixtures.SQL。执行 python3 fixtures.py sample.db 创建旧库，路径必须未初始化。
meta 的 schema_version=1、generation=9。tracks_v1(track_id,points_json) 保存8条当前轨迹；region_v1(track_id,south,north) 保存旧纬度候选包络；receipts_v1(request_id,payload,receipt) 保存9份请求绑定及回执原文。
payload 是 model.dump([track_id,规范坐标列表])，receipt 是 model.dump(回执字典)；model.dump 的无空格、非ASCII保真、键排序是既有序列化。SQL内已有历史 r7、r8：同一 replace 先跨线后改到0°，r7仍应返回第7代回执。
例：search(179500000,400000,-179500000,600000) 返回 ["clone","cross","edge"]；search(500000,500000,500000,500000) 返回 ["ordinary"]。cross 原文为 [[179000000,0],[-179000000,1000000]]。tie 从90°到-90°走负方向，命中0°而不命中180°。point 的-180°到180°是同位置退化线段。

## SDK2与目标表
plane2.install(conn) 创建以下真实目标存储，不修改 meta，也不自行提交：
- sdk2_tracks(track_id TEXT PRIMARY KEY,original_json TEXT NOT NULL)
- sdk2_receipts(request_id TEXT PRIMARY KEY,payload TEXT NOT NULL,receipt TEXT NOT NULL)
- sdk2_piece(piece_id INTEGER PRIMARY KEY,track_id TEXT NOT NULL REFERENCES sdk2_tracks(track_id),coords TEXT NOT NULL)，并有 track_id 索引
- sdk2_box USING rtree(piece_id,minx,maxx,miny,maxy)
完整可执行DDL在 plane2.DDL。旧三表须逐字保留作审计；切换后不再更新或用它们供业务查询。meta.schema_version 作为原子可见的切换标记，升级后为2，generation沿用。
plane2.replace(conn,track_id,original,pieces) 在调用方事务中替换目标原文及全部所属平面片段，自动清理旧片段及其RTree行；不修改请求账或代次。pieces 是非空序列，每项为两个平面端点，如 [((0,0),(1000000,1000000))]。坐标接受整数、Fraction或分数字符串；x限于±540000000，y限于±90000000。有理坐标精确保存，RTree只作保守候选；它不理解周期经度，也不检验 original 与 pieces 的业务一致性。
plane2.get(conn,track_id) 返回目标原文或None。plane2.candidates(conn,w,s,e,n) 是生成器，接受有理数且 w<=e、s<=n 的闭合平面框，经RTree返回 (track_id,精确片段)，可能重复ID或有包络误报；plane2.intersects(piece,(w,s,e,n)) 作精确平面相交。SDK2允许有理数交点、边界重合及退化片段；不提供周期归一化、切分、查询平移或身份去重策略。
plane2.native_put(conn,request_id,track_id,original,pieces) 是SDK2原生写入：只在schema_version=2时工作，以独立事务共同更新目标轨迹、所属索引、目标回执及代次，重放语义同旧 put。调用方负责提供符合交付表示不变量的片段；请求绑定以原始坐标为准，不包含其派生片段。普通非跨线原生示例：
original=[[30000000,-20000000],[31000000,-19000000]]，pieces=[original]；原生写入后旧 get/search 必须立即可见该轨迹。
两代 SDK 的 CALLS 列表仅供核账，不是持久状态。SDK源文件及冻结样本不应修改；归档、检索及新增迁移适配由做题者实现。

## 本次迁移与查询边界
新增 migration.upgrade(path,checkpoint=None)，成功返回 None；path 是已有SQLite文件，不是空库。限定维护窗口单工作者，无并发旧写，无在线追赶。
升级须原子迁入全部当前轨迹和全部请求回执，保留轨迹身份、原始坐标、请求绑定、代次及旧回执原文；不把历史请求当成当前轨迹。失败或提交前进程终止后旧库内容和Schema不变，重开可重试；重复升级无副作用。
第一次升级在全部目标数据准备完成、修改schema_version为2之后、最终提交之前，调用 checkpoint("before_commit")（若提供）。回调异常必须回滚并原样传播；不得自行捕获进程终止。此钩子只用于确定性核验原子边界，不要求自建恢复框架。
已构造的 Store 对象也必须观察升级；切换后保留原接口，坐标与空间索引只能经SDK2目标存储读写，不能调用SDK1旁路。兼容层可直接读写 meta 和 sdk2_receipts；旧表仅供审计。后续旧 put 替换轨迹须和索引、回执共同原子生效；SDK2已提供的所属片段清理能力无需重写。
目标表示由交付者选择，必须在迁移、兼容put、SDK2原生续写和区域检索间一致。查询只读取由SDK2框索引返回的候选片段，并做精确过滤、排序去重；不得扫描全部原文或另建一套周期几何存储绕过SDK2。局部窗口不得用全球框取得全部候选再筛选；全球窗口的真实全部命中不受此限。
不要求在线迁移、多工作者、球面距离、任意多边形或通用GIS引擎。

## 核验与交付
python3 checks.py 是当前可执行的旧业务及平面SDK回归；python3 checks.py demo 展示真实旧查询、原文、历史重放及当前替换。
python3 upgrade_probe.py 是交付后的公开集成核验入口：保留旧断言，经冻结旧库验证升级、原回执、旧对象可见性、替换、SDK2原生续写、异常回滚、提交前真实子进程被杀后重试及重复升级。python3 upgrade_probe.py demo 同时输出真实升级结果。它不是目标实现，迁移尚未交付时不能通过；此脚本的基础探针不替代交付者必要的边界回归。
补充独立周期参照，不能调用目标表示转换或SDK1来充当独立判定器；核对180°两方向平局、±180°等价、折返、多段重复命中、非整数边界交点、全球框和退化框。通过SDK调用记录、查询计划及选择性窗口案例核验目标索引路径。测试可扩展，原有业务断言不得删除或弱化。
交付简短的表示不变量、归档—检索联动和迁移提交边界说明，记录实际验证结果。
运行清单 .pointwise-runtime.json 已提供：version为1、kind为cli，setup是准备命令的argv数组列表，verify/demo分别是核验/演示的argv数组。交付时verify改为 ["python3","upgrade_probe.py"]，demo改为 ["python3","upgrade_probe.py","demo"]；若新增回归，应使该核验入口一并执行。verify须核对业务结果，demo须展示真实迁移后行集。
