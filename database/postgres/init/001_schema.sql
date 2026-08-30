BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE user_role AS ENUM ('admin', 'dosen', 'mahasiswa');
CREATE TYPE question_type AS ENUM ('isian_singkat', 'esai');
CREATE TYPE difficulty_level AS ENUM ('mudah', 'sedang', 'sulit');
CREATE TYPE assessment_type AS ENUM ('bab', 'pretest', 'posttest');
CREATE TYPE attempt_status AS ENUM ('dikerjakan', 'menunggu_penilaian', 'dinilai');
CREATE TYPE answer_status AS ENUM ('menunggu_penilaian', 'dinilai');

-- PostgreSQL adalah source of truth untuk identitas dan autentikasi.
CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    nama varchar(160) NOT NULL,
    nim varchar(64) NOT NULL,
    password_hash text NOT NULL,
    role user_role NOT NULL,
    aktif boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT users_nim_trimmed CHECK (nim = btrim(nim) AND nim <> '')
);
CREATE UNIQUE INDEX users_nim_uq ON users (nim);
CREATE INDEX users_role_active_idx ON users (role, aktif);

-- module_id/bab_id adalah external ID yang canonical-nya berada di Neo4j.
CREATE TABLE enrollments (
    student_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    module_id varchar(200) NOT NULL,
    enrolled_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (student_id, module_id)
);
CREATE INDEX enrollments_module_idx ON enrollments (module_id);

-- Isi soal transaksional berada di PostgreSQL. Relasi soal -> konsep berada di Neo4j.
CREATE TABLE questions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    chapter_id varchar(200) NOT NULL,
    text text NOT NULL,
    type question_type NOT NULL,
    reference_answer text,
    difficulty difficulty_level,
    for_module_exam boolean NOT NULL DEFAULT false,
    created_by uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX questions_chapter_idx ON questions (chapter_id);
CREATE INDEX questions_module_exam_idx ON questions (for_module_exam) WHERE for_module_exam;

CREATE TABLE assessment_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    module_id varchar(200) NOT NULL,
    chapter_id varchar(200),
    type assessment_type NOT NULL,
    status attempt_status NOT NULL DEFAULT 'dikerjakan',
    started_at timestamptz NOT NULL DEFAULT now(),
    submitted_at timestamptz,
    graded_at timestamptz,
    CONSTRAINT attempt_scope_ck CHECK (
        (type = 'bab' AND chapter_id IS NOT NULL) OR
        (type IN ('pretest', 'posttest') AND chapter_id IS NULL)
    )
);
CREATE UNIQUE INDEX one_module_exam_attempt_uq
    ON assessment_attempts (student_id, module_id, type)
    WHERE type IN ('pretest', 'posttest');
CREATE INDEX attempts_student_status_idx ON assessment_attempts (student_id, status);
CREATE INDEX attempts_grading_queue_idx ON assessment_attempts (status, submitted_at)
    WHERE status = 'menunggu_penilaian';

-- Snapshot pemilihan soal menjaga isi ujian stabil walaupun bank soal berubah.
CREATE TABLE attempt_questions (
    attempt_id uuid NOT NULL REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    question_id uuid NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
    position integer NOT NULL CHECK (position > 0),
    PRIMARY KEY (attempt_id, question_id),
    UNIQUE (attempt_id, position)
);

CREATE TABLE answers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id uuid NOT NULL,
    question_id uuid NOT NULL,
    text text NOT NULL,
    score numeric(5,2),
    status answer_status NOT NULL DEFAULT 'menunggu_penilaian',
    answered_at timestamptz NOT NULL DEFAULT now(),
    graded_at timestamptz,
    graded_by uuid REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT answers_attempt_question_fk
        FOREIGN KEY (attempt_id, question_id)
        REFERENCES attempt_questions(attempt_id, question_id) ON DELETE CASCADE,
    CONSTRAINT answers_score_ck CHECK (score IS NULL OR score BETWEEN 0 AND 100),
    CONSTRAINT answers_graded_state_ck CHECK (
        (status = 'menunggu_penilaian' AND score IS NULL AND graded_at IS NULL) OR
        (status = 'dinilai' AND score IS NOT NULL AND graded_at IS NOT NULL)
    ),
    UNIQUE (attempt_id, question_id)
);
CREATE INDEX answers_grading_queue_idx ON answers (status, answered_at)
    WHERE status = 'menunggu_penilaian';

-- Outbox adalah batas konsistensi: worker memproyeksikan perubahan soal ke Neo4j.
CREATE TABLE graph_outbox (
    id bigserial PRIMARY KEY,
    aggregate_type varchar(80) NOT NULL,
    aggregate_id varchar(200) NOT NULL,
    event_type varchar(120) NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    last_error text
);
CREATE INDEX graph_outbox_pending_idx ON graph_outbox (id) WHERE processed_at IS NULL;

COMMIT;
