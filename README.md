# astrbot_msg_hook

HTTP 消息转发插件，通过 HTTP 接口接收消息并转发到指定 QQ 群。

## 功能特性

- HTTP 接口接收外部消息请求
- 支持多个目标群号同时接收消息
- 支持 API Token 认证保护接口
- 支持消息前缀和后缀自定义
- 支持在群聊内通过指令快速启用消息转发
- 可通过 WebUI 配置所有参数

## 安装

1. 将插件文件夹放置到 AstrBot 的 `plugins` 目录下
2. 重启 AstrBot 或在插件管理中启用本插件

## 配置

在 AstrBot WebUI 的插件配置页面中配置以下参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| server_host | HTTP 服务器监听地址 | 127.0.0.1 |
| server_port | HTTP 服务器端口 | 8080 |
| api_token | API 访问令牌（留空则不验证） | 空 |
| target_groups | 目标 QQ 群号列表 | 空 |
| target_sessions | 目标群会话标识（由指令自动维护） | 空 |
| enable_forward | 启用消息转发 | true |
| message_prefix | 消息前缀 | 空 |
| message_suffix | 消息后缀 | 空 |

**注意：** 如果需要从外部访问 HTTP 接口，请将 `server_host` 设置为 `0.0.0.0`，并建议设置 `api_token` 以保护接口安全。

## 使用方法

### 1. 发送消息

向插件发送 HTTP POST 请求：

```bash
curl -X POST http://127.0.0.1:8080/send \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"message": "这是一条测试消息"}'
```

**请求参数：**
- `message` (必需): 要发送的消息内容

**响应示例：**
```json
{
  "success": true,
  "message": "消息已发送到 1/1 个群"
}
```

### 2. 健康检查

查看插件运行状态：

```bash
curl http://127.0.0.1:8080/health
```

**响应示例：**
```json
{
  "status": "ok",
  "target_groups": [123456789],
  "server": {
    "host": "127.0.0.1",
    "port": 8080
  },
  "enable_forward": true
}
```

### 3. 机器人指令

在 QQ 群中发送以下指令：

- `/msg_status` - 查看插件当前状态
- `/开启消息` - 将当前群聊加入消息转发目标列表；重复执行不会重复添加

## API Token 认证

如果配置了 `api_token`，需要在请求头中携带：

```
Authorization: Bearer YOUR_TOKEN
```

也兼容直接传入令牌的写法：

```
Authorization: YOUR_TOKEN
```

## 示例场景

### Python 示例

```python
import requests

url = "http://127.0.0.1:8080/send"
headers = {
    "Content-Type": "application/json",
    "Authorization": "Bearer YOUR_TOKEN"
}
data = {"message": "来自 Python 的消息"}

response = requests.post(url, json=data, headers=headers)
print(response.json())
```

### Node.js 示例

```javascript
const axios = require('axios');

axios.post('http://127.0.0.1:8080/send', {
  message: '来自 Node.js 的消息'
}, {
  headers: {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer YOUR_TOKEN'
  }
}).then(response => {
  console.log(response.data);
});
```

## 开源协议

本项目采用 MIT 协议开源。
