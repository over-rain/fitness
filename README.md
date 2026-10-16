# 个人减肥管家（fitness）

「怕麻烦的人的减肥管家」：拍照/说话记饮食 → 热量预算自动扣除 → 告诉你能吃多少、建议怎么吃；训练一句话记录 → 达标判断 → 周复盘优化。

## 目录结构

```
fitness\
├── code\                 # 代码
│   ├── run_server.py     #   本地照片接收端（零依赖，python 标准库）
│   └── scripts\
│       └── fitness_lib.py#   热量/BMR/宏量计算（Mifflin-St Jeor）
├── docs\                 # 文档（索引见 docs\README.md，编号即阅读顺序）
│   ├── 01-需求文档.md    #   v0.3 定位定稿 + 第 12 节「扣子先行」分支方案
│   ├── 02-扣子搭建指南.md#   扣子 coze.cn 搭建步骤（人设提示词/数据库/知识库/发布）
│   └── 03-Coze迁移包.md  #   平台无关的设计资产（工作流模式/提示词/表结构/避坑）
└── data\                 # 数据（运行期读写）
    ├── profile.json      #   身体档案骨架
    ├── meals\            #   上传的餐食照片
    ├── plans\            #   周训练计划
    └── meal_log.jsonl    #   餐食记录（上传端运行后生成）
```

## 快速操作

| 场景 | 命令 |
|---|---|
| **起减肥管家 v1（拍照记餐+剩余）** | `cd code && python app.py`（部署详见 `docs\05-本地部署指南.md`） |
| 起旧照片接收端 | `cd code && python run_server.py`（新位置路径自动取上一级 data\） |
| 算热量线 | `PYTHONIOENCODING=utf-8 python code/scripts/fitness_lib.py calories 170 65 30 male fat_loss 4` |
| 看需求 | 打开 `docs\01-需求文档.md` |
| 扣子先行试验 | 打开 `docs\02-扣子搭建指南.md`，2 周验收标准见需求文档第 12.2 |

## 当前路线

**扣子先行试验 2 周**（2026-10 起，验收不过→回自建）：识别引擎可切换 DeepSeek/GLM。