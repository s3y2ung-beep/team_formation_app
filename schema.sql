-- 팀 편성 앱의 테이블. 6장 실습의 테이블과 같은 DB에 있으므로 이름을 모두 tf_ 로 시작함
-- 앱이 시작할 때 이 파일을 그대로 실행함(teamapp/db.py의 apply_schema). 여러 번 실행해도 안전함

-- 학생과 관리자. 비밀번호는 bcrypt 해시로만 저장함
create table if not exists tf_students (
    id            bigint generated always as identity primary key,
    student_no    text    not null unique,
    name          text    not null,
    main_role     text    check (main_role in ('기획자', '웹 프로그래머', '프론트엔드 디자이너', '테스터', '보고서 작성자', '발표자')),
    password_hash text    not null,
    is_admin      boolean not null default false,
    check (is_admin or main_role is not null)
);

-- 보조 역할. 학생 1명에 0~2행
create table if not exists tf_student_sub_roles (
    student_id bigint not null references tf_students(id) on delete cascade,
    role       text   not null check (role in ('기획자', '웹 프로그래머', '프론트엔드 디자이너', '테스터', '보고서 작성자', '발표자')),
    primary key (student_id, role)
);

-- 팀. id는 팀 번호(팀1의 1)와 같음
create table if not exists tf_teams (
    id   integer primary key,
    name text    not null unique
);

-- 팀원. (team_id, slot_no) 기본 키와 student_id 유일성 제약이
-- "마지막 자리에는 먼저 도착한 학생만 기록"과 "한 학생은 한 팀에만 소속"을 DB에서 지켜 줌
create table if not exists tf_members (
    team_id    integer     not null references tf_teams(id) on delete cascade,
    slot_no    integer     not null check (slot_no between 1 and 4),
    student_id bigint      not null unique references tf_students(id) on delete cascade,
    joined_at  timestamptz not null default now(),
    primary key (team_id, slot_no)
);

-- 지원
create table if not exists tf_applications (
    id         bigint generated always as identity primary key,
    team_id    integer     not null references tf_teams(id) on delete cascade,
    student_id bigint      not null references tf_students(id) on delete cascade,
    status     text        not null default '대기' check (status in ('대기', '승인', '거절')),
    reason     text,
    created_at timestamptz not null default now(),
    decided_at timestamptz
);

-- 한 학생은 결과를 기다리는 지원을 1개만 가질 수 있음
create unique index if not exists tf_applications_one_pending
    on tf_applications (student_id) where status = '대기';

-- 투표. 한 팀원은 한 지원에 한 번만 투표함
create table if not exists tf_votes (
    application_id bigint      not null references tf_applications(id) on delete cascade,
    voter_id       bigint      not null references tf_students(id) on delete cascade,
    vote           text        not null check (vote in ('찬성', '거부')),
    created_at     timestamptz not null default now(),
    primary key (application_id, voter_id)
);

-- 마감 여부, 배정안, keepalive 시각 등
create table if not exists tf_settings (
    key   text primary key,
    value text not null
);

-- AI 호출 기록. 모델마다 시도 결과를 남김
create table if not exists tf_ai_logs (
    id          bigint generated always as identity primary key,
    created_at  timestamptz not null default now(),
    run_id      text        not null,
    attempt_no  integer     not null,
    model       text        not null,
    outcome     text        not null,
    elapsed_sec numeric(6, 1),
    detail      text
);

-- Supabase의 공개 API(anon 키)로는 이 테이블들을 읽고 쓰지 못하게 RLS를 켬
-- 앱은 테이블 주인 계정으로 접속하므로 RLS의 영향을 받지 않음
alter table tf_students          enable row level security;
alter table tf_student_sub_roles enable row level security;
alter table tf_teams             enable row level security;
alter table tf_members           enable row level security;
alter table tf_applications      enable row level security;
alter table tf_votes             enable row level security;
alter table tf_settings          enable row level security;
alter table tf_ai_logs           enable row level security;
