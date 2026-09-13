# Git 远程 Tag 操作指南

本指南介绍 Git 标签（tag）的常用操作，重点覆盖与**远程仓库**相关的推送、拉取、删除等场景。

---

## 一、Tag 的两种类型

| 类型 | 说明 | 创建命令 |
| --- | --- | --- |
| 轻量标签（lightweight） | 只是某个提交的引用指针，不含额外信息 | `git tag v1.0.0` |
| 附注标签（annotated） | 独立对象，含标签作者、日期、说明、可签名，**推荐用于发布** | `git tag -a v1.0.0 -m "说明"` |

> 建议：正式版本发布使用附注标签，便于追溯。

---

## 二、创建 Tag

```bash
# 轻量标签（指向当前 HEAD）
git tag v1.0.0

# 附注标签（推荐）
git tag -a v1.0.0 -m "发布 1.0.0 版本"

# 给指定提交打标签
git tag -a v1.0.0 <commit-hash> -m "补打历史版本标签"
```

---

## 三、查看 Tag

```bash
# 列出所有本地标签
git tag

# 按模式过滤
git tag -l "v1.*"

# 查看某个标签的详细信息（附注标签）
git show v1.0.0
```

---

## 四、推送 Tag 到远程（核心）

创建标签后，默认 `git push` **不会**推送标签，需要显式推送。

```bash
# 推送单个标签
git push origin v1.0.0

# 推送本地所有标签
git push origin --tags

# 只推送附注标签（跳过轻量标签），Git 2.4+
git push origin --follow-tags
```

> 注意：`--tags` 会推送所有本地标签；`--follow-tags` 只推送随提交可达的附注标签，更安全。

---

## 五、拉取远程 Tag

```bash
# fetch 默认会自动获取可达的标签
git fetch

# 强制获取所有远程标签
git fetch --tags

# 拉取并覆盖本地同名标签（Git 2.20+）
git fetch --tags --force
```

---

## 六、删除 Tag

### 删除本地标签

```bash
git tag -d v1.0.0
```

### 删除远程标签

```bash
# 方式一（推荐，语义清晰）
git push origin --delete v1.0.0

# 方式二（旧写法：推送一个空引用到远程标签）
git push origin :refs/tags/v1.0.0
```

> 删除远程标签后，其他协作者本地仍可能残留该标签，需要各自 `git tag -d` 手动清理。

---

## 七、检出 / 切换到某个 Tag

标签指向固定提交，检出后处于「分离头指针（detached HEAD）」状态。

```bash
# 查看标签对应的代码
git checkout v1.0.0

# 若要在该标签基础上开发，应新建分支
git checkout -b hotfix-1.0.1 v1.0.0
```

---

## 八、常见问题与技巧

### 1. 推送了错误的标签，如何修正？
```bash
# 删除远程与本地错误标签
git push origin --delete v1.0.0
git tag -d v1.0.0
# 重新打标签并推送
git tag -a v1.0.0 <correct-commit> -m "修正"
git push origin v1.0.0
```

### 2. 移动已存在的标签到新提交（谨慎，会改写引用）
```bash
git tag -f -a v1.0.0 <new-commit> -m "重新指向"
git push origin -f v1.0.0
```
> 强制覆盖已发布的标签有风险，会影响已拉取该标签的协作者，非必要不要这样做。

### 3. 一次性清理本地已被远程删除的标签
```bash
git fetch --prune --prune-tags
```

### 4. 基于标签触发 CI/CD
许多 CI 系统（GitHub Actions、GitLab CI 等）可监听 tag 推送事件。只需 `git push origin vX.Y.Z` 即可触发对应的发布流水线。

---

## 九、命令速查表

| 目的 | 命令 |
| --- | --- |
| 创建附注标签 | `git tag -a v1.0.0 -m "msg"` |
| 推送单个标签 | `git push origin v1.0.0` |
| 推送所有标签 | `git push origin --tags` |
| 只推送附注标签 | `git push origin --follow-tags` |
| 拉取所有标签 | `git fetch --tags` |
| 删除本地标签 | `git tag -d v1.0.0` |
| 删除远程标签 | `git push origin --delete v1.0.0` |
| 查看标签详情 | `git show v1.0.0` |
| 清理失效远程标签 | `git fetch --prune --prune-tags` |

---

## 十、推荐工作流（版本发布）

```bash
# 1. 确认代码已提交并推送
git push origin main

# 2. 打附注标签
git tag -a v1.2.0 -m "Release v1.2.0"

# 3. 推送标签触发发布
git push origin v1.2.0
```
