DROP DATABASE IF EXISTS olympia_auth;
CREATE DATABASE olympia_auth;
USE olympia_auth;

CREATE TABLE users (
    user_id       INT AUTO_INCREMENT PRIMARY KEY,
    username      VARCHAR(50)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          ENUM('Admin', 'Player', 'Coach') NOT NULL DEFAULT 'Player',
    member_id     INT UNIQUE,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sessions (
    session_id  INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    token_hash  VARCHAR(255) NOT NULL UNIQUE,
    issued_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at  TIMESTAMP NOT NULL,
    is_revoked  BOOLEAN NOT NULL DEFAULT FALSE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE audit_log (
    log_id      BIGINT AUTO_INCREMENT PRIMARY KEY,
    timestamp   TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    user_id     INT,
    username    VARCHAR(50),
    action      VARCHAR(20)  NOT NULL,
    table_name  VARCHAR(50),
    record_id   VARCHAR(100),
    status      ENUM('SUCCESS','FAILURE','UNAUTHORIZED') NOT NULL,
    details     TEXT,
    ip_address  VARCHAR(45),
    prev_hash   VARCHAR(64)  NOT NULL,
    entry_hash  VARCHAR(64)  NOT NULL
);
