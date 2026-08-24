# 需求文档 §8.2 核心表DDL

来源：docs/design-doc-raw.xml 提取

8.2 核心表DDL
##### 8.2.1 project（项目表）
CREATE TABLE project (
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
name VARCHAR(50) NOT NULL,
code VARCHAR(20) NOT NULL UNIQUE,
description VARCHAR(500),
target_url VARCHAR(500) NOT NULL DEFAULT 'http://localhost:81',
status VARCHAR(10) DEFAULT 'active',
created_by VARCHAR(50) NOT NULL,
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
is_deleted BOOLEAN DEFAULT FALSE
);
##### 8.2.2 page_repository（页面仓库表）
CREATE TABLE page_repository (
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
project_id UUID NOT NULL REFERENCES project(id) ON DELETE RESTRICT,
page_name VARCHAR(50) NOT NULL,
url_path VARCHAR(200) NOT NULL,
screenshot_url TEXT,
element_count INTEGER DEFAULT 0,
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
UNIQUE(project_id, url_path)
);
CREATE INDEX idx_page_repo_project ON page_repository(project_id);
##### 8.2.3 element_repository（元素仓库表）
CREATE TABLE element_repository (
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
page_id UUID NOT NULL REFERENCES page_repository(id) ON DELETE CASCADE,
alias VARCHAR(50) NOT NULL,
element_type VARCHAR(20) NOT NULL,
display_text VARCHAR(100),
coord_x INTEGER NOT NULL DEFAULT 0,
coord_y INTEGER NOT NULL DEFAULT 0,
width INTEGER NOT NULL DEFAULT 0,
height INTEGER NOT NULL DEFAULT 0,
locator_chain JSONB NOT NULL,
confidence INTEGER DEFAULT 0,
status VARCHAR(10) DEFAULT 'active',
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
UNIQUE(page_id, alias)
);
CREATE INDEX idx_element_repo_page ON element_repository(page_id);
##### 8.2.4 test_point（测试点表）
CREATE TABLE test_point (
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
project_id UUID NOT NULL REFERENCES project(id) ON DELETE RESTRICT,
page_name VARCHAR(50) NOT NULL,
name VARCHAR(100) NOT NULL,
type_label VARCHAR(20) NOT NULL,
description VARCHAR(500),
source_ref VARCHAR(500),
status VARCHAR(20) DEFAULT 'pending',
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_test_point_project ON test_point(project_id);
##### 8.2.5 test_case（用例表）
CREATE TABLE test_case (
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
project_id UUID NOT NULL REFERENCES project(id) ON DELETE RESTRICT,
point_id UUID REFERENCES test_point(id) ON DELETE SET NULL,
name VARCHAR(100) NOT NULL,
priority VARCHAR(2) NOT NULL DEFAULT 'P1',
case_type VARCHAR(20) NOT NULL DEFAULT 'functional',
automation_status VARCHAR(20) DEFAULT 'pending',
precondition TEXT,
steps JSONB NOT NULL,
expected_result VARCHAR(200) NOT NULL,
is_finalized BOOLEAN DEFAULT FALSE,
version INTEGER DEFAULT 1,
hallucination_status VARCHAR(20) DEFAULT 'normal',
created_by VARCHAR(50),
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
is_deleted BOOLEAN DEFAULT FALSE,
UNIQUE(project_id, name)
);
CREATE INDEX idx_test_case_project ON test_case(project_id);
CREATE INDEX idx_test_case_automation ON test_case(automation_status);
##### 8.2.6 script_asset（脚本资产表）
CREATE TABLE script_asset (
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
case_id UUID NOT NULL REFERENCES test_case(id) ON DELETE CASCADE,
content TEXT NOT NULL,
version INTEGER DEFAULT 1,
status VARCHAR(20) DEFAULT 'generated',
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_script_case ON script_asset(case_id);
##### 8.2.7 execution_record（执行记录表）
CREATE TABLE execution_record (
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
exec_id VARCHAR(50) UNIQUE NOT NULL,
project_id UUID NOT NULL REFERENCES project(id) ON DELETE RESTRICT,
exec_type VARCHAR(20) NOT NULL,
status VARCHAR(20) NOT NULL,
total_cases INTEGER DEFAULT 0,
passed_count INTEGER DEFAULT 0,
fail_count INTEGER DEFAULT 0,
pass_rate DECIMAL(5,2) DEFAULT 0,
duration_ms INTEGER DEFAULT 0,
tokens_used INTEGER DEFAULT 0,
env_info JSONB,
report_url TEXT,
started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
finished_at TIMESTAMP
);
CREATE INDEX idx_exec_record_project ON execution_record(project_id);
CREATE INDEX idx_exec_record_time ON execution_record(started_at DESC);
##### 8.2.8 self_heal_cache（自愈合缓存表）
CREATE TABLE self_heal_cache (
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
element_id UUID NOT NULL REFERENCES element_repository(id) ON DELETE CASCADE,
locator_value VARCHAR(500) NOT NULL,
confidence INTEGER DEFAULT 1,
hit_count INTEGER DEFAULT 0,
fail_count INTEGER DEFAULT 0,
ttl_days INTEGER DEFAULT 30,
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_heal_element ON self_heal_cache(element_id);
CREATE INDEX idx_heal_confidence ON self_heal_cache(confidence DESC);
##### 8.2.9 ai_call_log（AI调用日志表）
CREATE TABLE ai_call_log (
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
project_id UUID NOT NULL REFERENCES project(id) ON DELETE RESTRICT,
model VARCHAR(50) NOT NULL,
tokens_used INTEGER DEFAULT 0,
tokens_cost DECIMAL(10,4) DEFAULT 0,
stage VARCHAR(30) NOT NULL,
status VARCHAR(20) DEFAULT 'success',
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_ai_log_project ON ai_call_log(project_id);
CREATE INDEX idx_ai_log_time ON ai_call_log(created_at DESC);
##### 8.2.10 knowledge_base（知识库表·整合新增）
CREATE TABLE knowledge_base (
id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
project_id UUID NOT NULL REFERENCES project(id) ON DELETE RESTRICT,
content_type VARCHAR(20) NOT NULL,
title VARCHAR(200) NOT NULL,
content TEXT NOT NULL,
source VARCHAR(20) NOT NULL,
tags VARCHAR(200),
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_kb_project ON knowledge_base(project_id);
