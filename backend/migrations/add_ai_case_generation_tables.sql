-- backend/migrations/add_ai_case_generation_tables.sql

-- 启用pgvector扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 测试规则表
CREATE TABLE IF NOT EXISTS test_rule (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL,
    description TEXT NOT NULL,
    prompt_template TEXT,
    is_builtin BOOLEAN DEFAULT FALSE,
    status VARCHAR(20) DEFAULT 'active',
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 知识文档表
CREATE TABLE IF NOT EXISTS knowledge_document (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES project(id),
    doc_name VARCHAR(200) NOT NULL,
    doc_type VARCHAR(20) NOT NULL,
    file_url TEXT,
    content TEXT,
    chunk_count INTEGER DEFAULT 0,
    vector_status VARCHAR(20) DEFAULT 'pending',
    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 知识分块表
CREATE TABLE IF NOT EXISTS knowledge_chunk (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES knowledge_document(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(1536),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 创建向量索引
CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_embedding ON knowledge_chunk
USING ivfflat (embedding vector_cosine_ops);

-- 生成会话表
CREATE TABLE IF NOT EXISTS generation_session (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES project(id),
    document_content TEXT,
    selected_rules JSONB,
    selected_knowledge JSONB,
    hallucination_strategy VARCHAR(20),
    current_step INTEGER DEFAULT 1,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 幻觉检测配置表
CREATE TABLE IF NOT EXISTS hallucination_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    config_type VARCHAR(50) NOT NULL,
    config_value TEXT NOT NULL,
    description VARCHAR(200),
    is_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 插入默认禁用词
INSERT INTO hallucination_config (config_type, config_value, description) VALUES
('forbidden_keyword', '观察', '非自动化词汇'),
('forbidden_keyword', '查看', '非自动化词汇'),
('forbidden_keyword', '验证', '非自动化词汇'),
('forbidden_keyword', '检查', '非自动化词汇'),
('forbidden_keyword', '确认', '非自动化词汇');

-- 插入默认测试规则
INSERT INTO test_rule (name, description, is_builtin, prompt_template) VALUES
('自动化思维规则', '强制所有步骤使用可自动化的操作描述', TRUE,
 '要求：所有测试步骤必须使用明确的操作动词（点击/输入/选择），禁止使用"观察/查看/验证"等非自动化词汇'),
('边界值分析', '识别输入字段的边界值测试点', TRUE,
 '针对所有输入字段，识别以下测试点：最小值、最大值、最小值-1、最大值+1、空值'),
('等价类划分', '将输入划分为有效和无效等价类', TRUE,
 '识别每个输入的有效等价类和无效等价类，每类至少一个测试点'),
('场景法', '识别典型业务场景的测试点', TRUE,
 '识别用户的典型使用场景、异常场景、极端场景'),
('状态迁移', '识别状态变化相关的测试点', TRUE,
 '识别系统各状态及状态间的迁移路径');
