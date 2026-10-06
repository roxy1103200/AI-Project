-- 用户记忆以 MySQL 为准；Chroma 是可重建索引，不参与业务事务。
CREATE TABLE IF NOT EXISTS ai_user_memory (
  id CHAR(36) PRIMARY KEY,
  user_id BIGINT NOT NULL,
  channel VARCHAR(8) NOT NULL DEFAULT 'AGENT',
  category VARCHAR(32) NOT NULL DEFAULT 'GENERAL',
  content VARCHAR(500) NOT NULL,
  source_kind VARCHAR(24) NOT NULL DEFAULT 'EXPLICIT',
  source_message_id CHAR(36) NULL,
  version INT NOT NULL DEFAULT 1,
  status VARCHAR(12) NOT NULL DEFAULT 'ACTIVE',
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  deleted_at DATETIME NULL,
  INDEX idx_ai_memory_owner (user_id, channel, status, updated_at),
  CONSTRAINT fk_ai_memory_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ai_memory_index_outbox (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  memory_id CHAR(36) NOT NULL,
  version INT NOT NULL,
  state VARCHAR(12) NOT NULL DEFAULT 'PENDING',
  attempts INT NOT NULL DEFAULT 0,
  available_at DATETIME NOT NULL,
  lease_token CHAR(36) NULL,
  lease_until DATETIME NULL,
  created_at DATETIME NOT NULL,
  UNIQUE KEY uk_ai_memory_event (memory_id, version),
  INDEX idx_ai_memory_jobs (state, available_at, id),
  INDEX idx_ai_memory_order (memory_id, state, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
