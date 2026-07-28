# SemanticState 设计

## 1. 为什么需要非文本状态

embedding 属于数值状态。把它转为长字符串塞入 Prompt 会放大文本传输、破坏数值精度，也无法清晰统计非文本传输。MemLink 将向量独立存储，只传递引用。

## 2. 向量生成

Retriever 对任务主题和问题生成查询向量；Reviewer 对验证通过的任务主题、问题和结论生成记忆向量。接口统一为异步 `EmbeddingClient.embed(text)`。

## 3. Fake embedding 的确定性

FakeEmbeddingClient 使用带计数器的 SHA-256 扩展输入字节，转换为 `float32` 后归一化。相同文本和维度得到完全相同的向量，不使用网络或随机服务。

## 4. 真实 embedding 适配

现有 `OpenAICompatibleEmbeddingClient` 仍可用于独立的 embedding 兼容端点，
并校验返回是一维且维度匹配。DeepSeek 人工演示不假设其提供 embedding API，
因此明确使用可复现的 Fake Embedding；真实 LLM 输出不会改变 NumPy 二进制
状态与 `semantic_state_id` 的传递方式。

## 5. 向量存储

StateStore 将连续浮点数组保存为禁止 pickle 的 `.npy`，元数据保存为同 ID 的 UTF-8 JSON。写入先使用临时文件，再原子替换。

## 6. state_id

每次保存生成 UUID。`storage_ref` 仅保存相对文件名，避免把 Windows 或 Linux 绝对路径写入协议。

## 7. structured 消息引用

`AgentMessage.semantic_state_ids` 保存 UUID。完整 structured 在计划、检索和执行请求中传递查询状态 ID，并按实际向量字节统计传输。

## 8. 下游读取和使用

Orchestrator 根据 state ID 调用 `get_metadata()` 或 `load()`。页面只调用前者；向量检索调用后者。读取向量时执行完整性校验。

## 9. 相似度检索

MemoryStore 加载候选记忆的状态向量，检查 shape 后计算余弦相似度，并把 `[-1,1]` 映射为 `[0,1]` 排序分数。

## 10. dimensions、dtype、byte_size

- `dimensions`：一维向量元素数；
- `dtype`：当前 Fake 为 `float32`；
- `byte_size`：原始连续数组字节数，不是 `.npy` 文件大小。

## 11. content_hash

保存时对连续数组原始字节计算 SHA-256。读取时重新计算，检测损坏或不一致。

## 12. 生命周期

普通运行使用配置目录长期保存；Benchmark 每个实验使用临时目录，实验结束删除。状态元数据在 StateStore 初始化时恢复索引。

## 13. 文件清理

Benchmark 通过 `TemporaryDirectory` 清理实验状态，并记录清理结果。生产数据清理必须在停止服务、确认目录后由维护者执行，不提供页面删除按钮。

## 14. 安全和隐私

状态可能隐含输入语义，应按业务数据保护。页面不展示向量，结果文件不保存 API Key，`allow_pickle=False` 避免加载任意 Python 对象。

## 15. 与 embedding 字符串化的区别

本实现的传输对象是 state ID，向量始终以 NumPy 二进制存在；字符串提示中没有向量列表。传输次数和引用字节单独计量。

## 16. 当前限制

StateStore 是单机文件实现，没有分布式对象存储、垃圾回收策略、加密或访问控制。当前“非文本状态”用于检索与路由，不是模型隐藏层状态。
