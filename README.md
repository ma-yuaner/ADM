# ADM分配工作台

用于解决ADM处理人员无法快速识别本人订单、负责人需要逐单转单的问题。

第一版只提供：

- 我的待办、团队待办、全部未结案；
- 按数据源、预警等级、订单号筛选；
- 单张快速转单、批量分配实际处理人；
- 按`ota_code`套用字段配置并导出Excel；
- 不新增数据库表，复用`adm_records`和`auto_issue_operator_log`。

## 技术结构

```text
浏览器 -> Flask API -> sibedb.adm_records
                    -> sibedb.auto_issue_operator_log
                    -> Excel下载
```

前端是原生HTML/CSS/JavaScript，由Flask直接提供；生产环境使用Gunicorn和单个Docker容器。

## 本地运行

### 1. 创建环境

```powershell
cd D:\data_team_repo\data-team-repo\adm_assignment_demo
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

### 2. 使用演示数据启动

无需创建`.env`，默认使用mock数据：

```powershell
.\.venv\Scripts\python.exe app.py
```

访问：

```text
http://127.0.0.1:5050
```

### 3. 连接仓库现有ERP配置

复制`.env.example`为`.env`，修改：

```env
ADM_DATA_MODE=repo
ADM_WRITE_ENABLED=false
```

`repo`模式通过`common_libs.config.db_config.erp_config.get_connect()`连接`sibedb`，适合在完整的`data-team-repo`目录中运行。

先保持只读，确认列表、人员和Excel正确后，再在测试库设置：

```env
ADM_WRITE_ENABLED=true
```

### 4. 独立Docker环境连接MySQL

Docker镜像不复制公司仓库中的数据库配置，必须通过环境变量连接：

```env
ADM_DATA_MODE=mysql
ADM_WRITE_ENABLED=false
ADM_DB_HOST=数据库地址
ADM_DB_PORT=3306
ADM_DB_USER=数据库用户
ADM_DB_PASSWORD=数据库密码
ADM_DB_DATABASE=sibedb
```

## 数据口径

未结案条件：

```sql
status = 1
AND COALESCE(adm_status, -1) <> 3
```

我的待办：

```sql
actual_owner = 当前人员
OR (actual_owner为空 AND owner=当前人员)
```

团队待办：

```sql
owner = 当前负责人
```

分配动作在一个事务中：

1. 锁定并检查ADM仍有效且未结案；
2. 更新`adm_records.actual_owner`；
3. 向`auto_issue_operator_log`写入“实际责任人由A修改为B”；
4. 任一步失败则整体回滚。

## Excel模板配置

配置文件：`config/export_profiles.json`。

配置键对应`adm_records.ota_code`。未单独配置的数据源使用`DEFAULT`列；一次导出包含多个数据源时，每个数据源一个Sheet。

## 自动测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

测试不连接真实数据库，也不会写入业务数据。

## Docker本地验证

```bash
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:5050/api/health
```

默认Docker Compose使用mock数据。

服务器从GitLab拉取源码、配置真实数据库并启动的完整命令，见[部署说明](docs/deployment.md#零从gitlab拉取源码直接启动测试服务器最简单方式)。

## 接口

| 方法 | 地址 | 说明 |
|---|---|---|
| GET | `/api/health` | 服务与数据库状态 |
| GET | `/api/config` | 页面运行配置 |
| GET | `/api/people` | 可选择人员 |
| GET | `/api/tasks` | ADM待办列表和统计卡 |
| POST | `/api/assign` | 批量分配实际处理人 |
| GET | `/api/export` | 导出数据源Excel |

列表参数：

```text
scope=mine|team|all
person=人员姓名
source=ota_code
alert=P0|P1|P2|NORMAL
search=ADM单号、OTA订单号或票号
page=1
pageSize=20
```

分配请求：

```json
{
  "admIds": [101, 102],
  "actualOwner": "李志君",
  "actor": "黄娜娟"
}
```

当前版本不登录，`actor`来自页面选择的“当前查看人员”。因此测试环境可用于业务流程确认，但不能把它当成可信的身份认证或考核依据。

部署与GitLab CI/CD见[部署说明](docs/deployment.md)。
