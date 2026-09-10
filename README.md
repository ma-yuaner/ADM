# ADM分配工作台

用于解决ADM处理人员无法快速识别本人订单、负责人需要逐单转单的问题。

第一版只提供：

- 我的待办、团队待办、全部未结案；
- 按数据源、预警等级、订单号筛选；
- 单张快速转单、批量分配实际处理人；
- 关联操作日志展示最近转单时间、转单前后人员、转单次数及转单后未接单状态；
- 将筛选后的不同平台数据统一导出到一个Excel工作表；
- 向企业微信群发送所选人员的全部未结案ADM清单并@本人；
- 核验财务差异库，导出“已录入差异 / 有差异单不是责任人录入 / 无差异单”；
- 业务在Excel末列填写恢复编码后回传，ADM专员在“编码恢复”页跟进处理；
- 将业务回传Excel转换为ADM管理系统的完整38列导入模板；
- 不新增业务库表，ADM读取仍复用`adm_records`和`auto_issue_operator_log`。

## 技术结构

```text
浏览器 -> Flask API -> sibedb.adm_records
                    -> sibedb.auto_issue_operator_log
                    -> ibf_prod_db.order_info_diff_reason（只读核验）
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
ADM_FINANCE_DIFF_ENABLED=true
ADM_FINANCE_DB_HOST=财务数据库地址
ADM_FINANCE_DB_PORT=3306
ADM_FINANCE_DB_USER=财务只读用户
ADM_FINANCE_DB_PASSWORD=财务数据库密码
ADM_FINANCE_DB_DATABASE=ibf_prod_db
```

财务核验的关联与责任人口径：

```text
adm_records.adm_no = order_info_diff_reason.ota_order_no
order_info_diff_reason.status = 1
ADM责任人 = actual_owner非空时取actual_owner，否则取owner
差异单录入人 = order_info_diff_reason.create_user_name
```

启用后的“处理进度”：存在有效差异且任一`create_user_name`与ADM责任人一致为“已录入差异”；存在有效差异但录入人均不一致为“有差异单不是责任人录入”；没有有效差异为“无差异单”。`duty_person`当前业务数据大量为空，仅作为辅助信息，不参与是否本人录入的判断。未启用时保留原有的“差异说明是否填写”默认判断。

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

页面查询也会读取该操作日志：`operator_datetime`作为转单时间；最新一次“实际责任人”变更作为最近转单；最近转单后没有“锁状态修改为已锁定”记录时，标记为“转单后未接单”。这些信息同时进入页面、下载Excel和企业微信群附件。

## 恢复编码跟进

1. 工作台导出或发送企业微信时，“系统”“PCC”“恢复编码”是末尾的黄色填写字段；
2. 业务填写编码后将原`.xlsx`文件回传；
3. ADM专员进入“编码恢复”，点击“导入填写后的Excel”；
4. 系统按ADM单号核对源数据，把有恢复编码的记录写入独立跟进库；
5. ADM专员将记录更新为待恢复、恢复中、已完成或异常。异常必须填写原因；
6. 同一ADM重复导入相同编码不会重复建单；编码变化时会重新转为待恢复。

恢复编码列表支持直接修改和删除。手工修改编码后会重置为“待恢复”并清空旧处理结果；删除只移除本服务的恢复跟进记录，可通过重新导入业务Excel恢复，不会删除`sibedb.adm_records`。

恢复编码跟进使用本服务自己的SQLite文件，不修改只读的`sibedb`。Docker部署通过`adm-recovery-data`卷持久化该文件。

## 业务回传转ADM导入模板

1. 业务人员在工作台导出的黄色字段中填写处理结果；
2. ADM专员进入“回传转换”，上传填写后的原`.xlsx`文件；
3. 服务按ADM单号重新读取`sibedb.adm_records`最新数据，作为完整导入底稿；
4. 差异说明、实际责任人、申诉状态、申诉原因、申诉结果和结案处理结果覆盖到底稿；
5. 当前阶段、确认结果、转单信息、处理进度、系统、PCC和恢复编码合并到`备注`；
6. 下载生成的38列Excel，核对后导入ADM管理系统。

状态转换口径：`待提交`转为待申诉；`已提交`转为申诉中；`不提交可结案`、申诉成功和申诉失败转为待审核。转换不会自动结案，仍由ADM专员在原系统审核。若数据库找不到ADM、同一ADM存在冲突行或业务字段超过明确长度，整次转换停止，不会静默丢行。历史备注按真实数据完整保留，不再按旧版200字表结构描述进行拦截或截断。

此功能只读源数据库并生成Excel，不要求开启`ADM_WRITE_ENABLED`，也不新增业务表。

## Excel模板配置

配置文件：`config/export_profiles.json`。

`DEFAULT.columns`定义统一导出字段及顺序；一次导出的不同平台数据全部放在`ADM待处理`工作表，并保留“平台”字段。

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
| GET | `/api/export` | 导出统一格式Excel |
| POST | `/api/adm-import/convert` | 业务回传Excel转ADM管理导入模板 |
| POST | `/api/recovery/import` | 导入业务填写的恢复编码 |
| PATCH | `/api/recovery/{id}` | 更新恢复处理状态和备注 |
| PATCH | `/api/recovery/{id}/code` | 修改错误编码并重置为待恢复 |
| DELETE | `/api/recovery/{id}` | 删除本服务的恢复编码跟进记录 |

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

## 企业微信发送

当前实现使用企业微信群机器人：先发送人员、未结案数量和提醒文字，再上传美化后的Excel，并通过企业微信user_id或手机号@所选人员。它不是一对一私聊。

服务器`.env`配置示例：

```env
ADM_WECOM_SEND_ENABLED=true
ADM_WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=机器人key
ADM_WECOM_PEOPLE_JSON={"黄娜娟":{"mobile":"企业微信手机号"},"李志君":{"user_id":"企业微信user_id"}}
```

人员姓名必须与页面下拉框完全一致。人员映射可选：未配置时仍会把清单发送到机器人所在群，并在正文写明处理人；配置后会额外@本人。页面只有人工点击并确认后才会发送，不包含自动定时推送。

部署与GitLab CI/CD见[部署说明](docs/deployment.md)。
