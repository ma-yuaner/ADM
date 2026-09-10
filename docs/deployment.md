# ADM分配工作台部署说明

## 零、从GitLab拉取源码直接启动（测试服务器最简单方式）

```bash
cd /opt
git clone https://git.ndccloud.com/analytics/adm.git adm-assignment-demo
cd /opt/adm-assignment-demo
cp .env.example .env
```

编辑`.env`，测试服务器连接真实库时至少配置：

```env
ADM_DATA_MODE=mysql
ADM_WRITE_ENABLED=false
ADM_DEFAULT_PERSON=黄娜娟
ADM_DB_HOST=数据库地址
ADM_DB_PORT=3306
ADM_DB_USER=数据库用户
ADM_DB_PASSWORD=数据库密码
ADM_DB_DATABASE=sibedb
ADM_HTTP_PORT=5050
```

需要启用企业微信群发送时追加：

```env
ADM_WECOM_SEND_ENABLED=true
ADM_WECOM_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=机器人key
ADM_WECOM_PEOPLE_JSON={"黄娜娟":{"mobile":"企业微信手机号"},"李志君":{"user_id":"企业微信user_id"}}
ADM_RECOVERY_DB_PATH=data/adm_recovery.db
ADM_UPLOAD_MAX_BYTES=10485760
```

该方式发送到机器人所在群，不是企业微信一对一私聊。人员手机号或user_id是可选配置：未配置时仍会发送并在正文写明处理人，配置后会额外@本人。页面只有人工点击并确认后才会发送。

启动并验证：

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 adm-assignment-demo
curl http://127.0.0.1:5050/api/health
```

`adm-recovery-data`是恢复编码跟进的持久化卷。普通`docker compose down`不会删除；不要执行`docker compose down -v`，否则会删除恢复编码跟进数据。

后续更新：

```bash
cd /opt/adm-assignment-demo
git pull origin main
docker compose up -d --build
curl http://127.0.0.1:5050/api/health
```

浏览器访问`http://测试服务器IP:5050`。如果其他电脑无法访问，需要开放服务器TCP 5050端口，或按本文Nginx示例配置内网域名。

## 一、仓库安排

建议把`adm_assignment_demo`目录作为独立Git仓库：

```text
GitLab：公司内部主仓库和部署来源
GitHub：代码备份或协作镜像
```

本地可配置两个远程地址：

```bash
git remote add origin <GitLab仓库地址>
git remote add github <GitHub仓库地址>
git push -u origin main
git push -u github main
```

GitLab识别项目根目录下的`.gitlab-ci.yml`。如果保留在`data-team-repo`单体仓库中，需要在仓库根CI文件中`include`本项目的流水线文件。

## 二、服务器首次准备

服务器需要：

- Docker Engine；
- Docker Compose插件；
- 能访问ERP MySQL；
- 能登录GitLab Container Registry。

准备目录：

```bash
sudo mkdir -p /opt/adm-assignment-demo
sudo chown <部署用户>:<部署用户> /opt/adm-assignment-demo
```

在服务器创建：

```text
/opt/adm-assignment-demo/.env
```

首次只读配置：

```env
ADM_DATA_MODE=mysql
ADM_WRITE_ENABLED=false
ADM_DEFAULT_PERSON=黄娜娟
ADM_OPERATOR_ID=0
ADM_DB_HOST=数据库地址
ADM_DB_PORT=3306
ADM_DB_USER=数据库用户
ADM_DB_PASSWORD=数据库密码
ADM_DB_DATABASE=sibedb
ADM_LOG_LEVEL=INFO
ADM_HTTP_PORT=5050
```

数据库账号需要：

- `adm_records`的SELECT权限；
- `auto_issue_operator_log`的SELECT权限；
- 验证列表和导出阶段不需要UPDATE/INSERT权限。

确认测试库分配流程后，再增加：

- `adm_records`的UPDATE权限；
- `auto_issue_operator_log`的INSERT权限；
- 将`ADM_WRITE_ENABLED`改为`true`。

## 三、GitLab CI/CD变量

进入GitLab项目：

```text
Settings -> CI/CD -> Variables
```

配置：

| 变量 | 内容 |
|---|---|
| `DEPLOY_HOST` | 测试服务器IP或域名 |
| `DEPLOY_USER` | SSH部署用户 |
| `DEPLOY_PATH` | `/opt/adm-assignment-demo` |
| `SSH_PRIVATE_KEY` | 部署私钥完整内容 |
| `SSH_KNOWN_HOSTS` | 测试服务器ssh-keyscan结果 |
| `REGISTRY_DEPLOY_USER` | GitLab Registry Deploy Token用户名 |
| `REGISTRY_DEPLOY_PASSWORD` | GitLab Registry Deploy Token密码 |

密码和私钥变量应设为Protected；能满足GitLab格式要求时同时设为Masked。

## 四、流水线过程

每次推送都会执行测试：

```text
pytest
```

推送`main`后：

1. 自动构建Docker镜像；
2. 推送`${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}`；
3. 推送`${CI_REGISTRY_IMAGE}:latest`；
4. 流水线出现手动任务`deploy_test`；
5. 人工点击后部署测试服务器；
6. 部署结束调用`/api/health`确认服务正常。

部署命令本质为：

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d --remove-orphans
curl http://127.0.0.1:5050/api/health
```

## 五、审核顺序

第一次部署按以下顺序验证：

1. `ADM_WRITE_ENABLED=false`启动；
2. 检查人员列表是否完整；
3. 检查团队待办、我的待办和全部未结案数量；
4. 按ADM单号抽查10张源表记录；
5. 按CTRIP、QUNAR等数据源导出Excel；
6. 审核各数据源字段和列顺序；
7. 切换到测试数据库账号；
8. 开启写入；
9. 选择一张测试ADM完成转单；
10. 核对`adm_records.actual_owner`；
11. 核对`auto_issue_operator_log`日志内容和版本号；
12. 运行流程快照ETL，确认该日志被识别为转单；
13. 刷新工作台，确认列表和Excel显示最近转单时间、转单前责任人、转单次数和转单状态；
14. 批量测试2至5张ADM；
15. 业务确认后再考虑生产部署。

## 六、Nginx示例

测试环境建议先使用独立域名，避免路径前缀影响静态资源：

```nginx
server {
    listen 80;
    server_name adm-demo.internal.example;

    client_max_body_size 20m;

    location / {
        proxy_pass http://127.0.0.1:5050;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

当前版本没有登录，域名必须只在公司内网开放，不建议直接暴露公网。

## 七、回滚

GitLab Registry保留每个提交SHA对应的镜像。回滚时指定上一版本：

```bash
cd /opt/adm-assignment-demo
export ADM_IMAGE=<GitLab镜像地址>:<上一版本提交SHA>
docker compose -f docker-compose.prod.yml up -d
curl http://127.0.0.1:5050/api/health
```

应用不新增数据库表。回滚镜像不会删除或反向修改已经完成的责任人变更，因此测试写入时必须只使用明确的测试ADM。
