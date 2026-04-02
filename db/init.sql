CREATE TABLE IF NOT EXISTS tokens (
    id SERIAL PRIMARY KEY,
    token VARCHAR(255) UNIQUE NOT NULL,
    label VARCHAR(255),
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tasks (
    uid UUID PRIMARY KEY,
    token_id INTEGER REFERENCES tokens(id) NOT NULL,
    state VARCHAR(2) NOT NULL DEFAULT 'PD',
    created_at TIMESTAMP DEFAULT NOW(),
    done_at TIMESTAMP,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS logs (
    id SERIAL PRIMARY KEY,
    token_id INTEGER REFERENCES tokens(id),
    action VARCHAR(50) NOT NULL,
    detail TEXT,
    ip VARCHAR(45),
    created_at TIMESTAMP DEFAULT NOW()
);
