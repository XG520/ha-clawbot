# 微信 ClawBot 自定义集成（Home Assistant）

将微信 ClawBot（iLink）接入 Home Assistant，实现二维码登录、消息收发和自动化通知。

## 功能

- 扫码登录 iLink（自动获取 bot_token）
- 后台长轮询接收微信消息
- 接收消息实体：显示最新收到的消息（只读）
- 发送消息实体：在仪表盘中输入并发送消息
- 通知实体：支持 Home Assistant 原生 `notify.send_message` 服务
- 自动跟踪最近发件人，方便直接回复

## 安装

1. 将 `ha-clawbot` 文件夹放到 Home Assistant 配置目录下的 `custom_components` 目录中：

   ```
   config/
   └─ custom_components/
      └─ ha-clawbot/
         ├─ __init__.py
         ├─ config_flow.py
         ├─ const.py
         ├─ hub.py
         ├─ manifest.json
         ├─ notify.py
         └─ text.py
   ```

2. 重启 Home Assistant。依赖 `segno>=1.5.0` 会在启动时自动安装。

## 配置

1. 进入 **设置 → 设备与服务 → 添加集成**，搜索并选择 **微信 ClawBot**
2. 输入实例名称（用于标识）
3. 页面会显示二维码，用微信扫码并确认登录
4. 扫码成功后自动创建集成和实体

## 实体

每个配置条目会创建以下实体：

| 实体 | 平台 | 说明 |
|------|------|------|
| `text.clawbot_接收消息` | Text | 显示最新收到的消息（只读），属性包含发件人 `from_user_id` 和 `context_token` |
| `text.clawbot_发送消息` | Text | 输入消息文本并发送，自动回复给最近发消息给你的人 |
| `notify.clawbot_通知` | Notify | 通知实体，支持原生 `notify.send_message` 服务 |

注意：由于微信官方限制，第一次使用需要在微信上主动发送一条消息，才能建立会话。

## 发送消息

### 方式一：通过发送消息实体

在仪表盘或开发者工具中调用 `text.set_value`：

```yaml
service: text.set_value
target:
  entity_id: text.clawbot_发送消息
data:
  value: "你好，这是一条测试消息"
```

### 方式二：通过原生通知服务

```yaml
service: notify.send_message
target:
  entity_id: notify.clawbot_通知
data:
  message: "你好，这是一条测试消息"
  title: "可选标题"
```

## 接收消息

当收到微信消息时，会触发事件 `ha_clawbot_message_received`，事件数据包含：

```yaml
event_type: ha_clawbot_message_received
data:
  entry_id: "配置条目ID"
  from_user_id: "发件人ID"
  text: "消息内容"
  context_token: "会话令牌"
  raw: "原始消息数据"
```

可在自动化中监听此事件：

```yaml
alias: 收到微信消息时通知
trigger:
  - platform: event
    event_type: ha_clawbot_message_received
action:
  - service: notify.mobile_app
    data:
      message: "收到微信消息：{{ trigger.event.data.text }}"
```

## 自动化示例

### 收到消息后自动回复

```yaml
alias: 自动回复微信消息
trigger:
  - platform: event
    event_type: ha_clawbot_message_received
action:
  - service: text.set_value
    target:
      entity_id: text.clawbot_发送消息
    data:
      value: "我已收到您的消息：{{ trigger.event.data.text }}"
```

### 定时发送通知

```yaml
alias: 每天定时发送微信通知
trigger:
  - platform: time
    at: "09:00:00"
action:
  - service: notify.send_message
    target:
      entity_id: notify.clawbot_通知
    data:
      message: "早上好！今天也要加油哦！"
      title: "每日提醒"
```

## 常见问题

- **发送消息失败：会话未建立** — 请先让对方发送一条消息，建立会话后再回复
- **没有实体显示** — 请确认集成已正确加载，尝试重启 Home Assistant
- **二维码无法显示** — 清除浏览器缓存或使用无痕模式重试
