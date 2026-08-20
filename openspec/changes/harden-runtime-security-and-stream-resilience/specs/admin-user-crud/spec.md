## MODIFIED Requirements

### Requirement: Admin can update user
系统 SHALL 扩展 `PUT /api/admin/users/{id}` 端点支持修改 `role_id`、`is_active` 等字段。管理员 MUST NOT 取消自己的管理员角色。每次敏感更新 MUST 在同一数据库事务中锁定操作者与目标账户，并拒绝操作者对当前角色高于自身的目标执行用户名、密码、状态、归档或角色变更。

#### Scenario: Change user role
- **WHEN** 管理员调用 `PUT /api/admin/users/{id}` 并设置可分配的 `role_id`
- **THEN** 系统更新用户角色并保留会话失效和最后超级管理员保护

#### Scenario: Admin cannot demote themselves
- **WHEN** 管理员尝试修改自己的 `role_id` 为非管理员角色
- **THEN** 系统返回 403 Forbidden，错误消息 "Cannot change your own role"

#### Scenario: Disable user account
- **WHEN** 管理员调用 `PUT /api/admin/users/{id}` 并设置 `is_active=false`
- **THEN** 系统禁用该用户账号，该用户后续登录请求返回 403

#### Scenario: Lower-role administrator targets a super administrator
- **WHEN** `dept_admin` 更新 `super_admin` 的用户名、密码、状态、归档或角色
- **THEN** 系统返回 403 Forbidden
