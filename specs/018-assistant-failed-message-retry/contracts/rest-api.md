# REST And Event Contract

## Retry Assistant Message

`POST /api/assistant/sessions/{sessionId}/retry`

Request:

```json
{
  "messageSequence": 7,
  "content": "optional edited replacement"
}
```

- Omitted `content`: retry the original user message.
- Present `content`: trim and dispatch as a new user turn; the original message is unchanged.

Success:

```json
{
  "accepted": true,
  "sessionId": "ast_abc",
  "messageSequence": 7
}
```

Errors:

- `404`: Assistant session not found.
- `409`: Target is not the current unresolved failed message, or another retry already claimed it.
- `422`: Edited content is empty or invalid.

## Assistant Message Failure Projection

```json
{
  "sequence": 7,
  "role": "user",
  "content": "Complete the report",
  "createdAt": "2026-06-15T10:00:00Z",
  "rendering": "plain_text",
  "failure": {
    "category": "network",
    "message": "连接模型服务时中断了。",
    "suggestion": "请检查网络后重试。",
    "attemptCount": 1,
    "failedAt": "2026-06-15T10:00:04Z"
  }
}
```

The same optional `failure` shape is allowed on `assistant.message`. It is valid only for a user message and contains no internal code, exception type, endpoint, response body, or credential.
