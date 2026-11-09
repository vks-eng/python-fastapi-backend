-- =============================================================================
-- TaskForge API: PostgreSQL schema (reference)
-- -----------------------------------------------------------------------------
-- GENERATED from the SQLAlchemy models (app/models) with the PostgreSQL dialect.
-- Alembic migrations (alembic/versions) are the SOURCE OF TRUTH; do not apply
-- this file to a database that is managed by Alembic. Use instead:
--     alembic upgrade head
-- Regenerate after any model change so this reference stays accurate.
-- =============================================================================

CREATE TYPE user_role AS ENUM ('user', 'admin');

CREATE TYPE task_status AS ENUM ('todo', 'in_progress', 'done', 'cancelled');

CREATE TYPE task_priority AS ENUM ('low', 'medium', 'high', 'urgent');

CREATE TABLE users (
	id UUID NOT NULL, 
	email VARCHAR(320) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	full_name VARCHAR(200), 
	role user_role DEFAULT 'user' NOT NULL, 
	is_active BOOLEAN DEFAULT 'true' NOT NULL, 
	last_login_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	CONSTRAINT pk_users PRIMARY KEY (id), 
	CONSTRAINT uq_users_email UNIQUE (email)
);

CREATE TABLE auth_sessions (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	last_used_at TIMESTAMP WITH TIME ZONE, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	revoked_reason VARCHAR(50), 
	user_agent VARCHAR(255), 
	ip_address VARCHAR(64), 
	CONSTRAINT pk_auth_sessions PRIMARY KEY (id), 
	CONSTRAINT fk_auth_sessions_user_id_users FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_auth_sessions_user_id_revoked_at ON auth_sessions (user_id, revoked_at);

CREATE TABLE tasks (
	id UUID NOT NULL, 
	owner_id UUID NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	description TEXT, 
	status task_status DEFAULT 'todo' NOT NULL, 
	priority task_priority DEFAULT 'medium' NOT NULL, 
	due_date TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	CONSTRAINT pk_tasks PRIMARY KEY (id), 
	CONSTRAINT ck_tasks_title_not_empty CHECK (char_length(title) > 0), 
	CONSTRAINT fk_tasks_owner_id_users FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_tasks_owner_id_created_at ON tasks (owner_id, created_at);

CREATE INDEX ix_tasks_owner_id_due_date ON tasks (owner_id, due_date);

CREATE INDEX ix_tasks_owner_id_priority ON tasks (owner_id, priority);

CREATE INDEX ix_tasks_owner_id_status ON tasks (owner_id, status);

CREATE TABLE refresh_tokens (
	id UUID NOT NULL, 
	session_id UUID NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	used_at TIMESTAMP WITH TIME ZONE, 
	CONSTRAINT pk_refresh_tokens PRIMARY KEY (id), 
	CONSTRAINT fk_refresh_tokens_session_id_auth_sessions FOREIGN KEY(session_id) REFERENCES auth_sessions (id) ON DELETE CASCADE, 
	CONSTRAINT uq_refresh_tokens_token_hash UNIQUE (token_hash)
);

CREATE INDEX ix_refresh_tokens_session_id ON refresh_tokens (session_id);
