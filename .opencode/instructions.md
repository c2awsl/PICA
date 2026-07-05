## 自动提交规则

每次完成修改后（新建/编辑文件、运行脚本等），必须自动提交到 git：

1. 先运行 `git status` 和 `git diff --cached` 了解改动内容
2. 用 `git add -A` 暂存所有改动
3. 用 `git commit -m "简明的英文描述"` 提交，描述要概括改动内容（如 "add ai_status column to Image model"）

如果用户明确说"不要提交"或"先别提交"，则跳过。提交信息用英文，简洁明确。