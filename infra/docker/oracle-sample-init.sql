-- Oracle sample database - sample data for source/target testing
-- Note: This runs as sys/oracle_dev_password@//localhost:1521/XE as sysdba

-- Create sample user and tablespace
CREATE TABLESPACE sample_ts DATAFILE SIZE 100M;

CREATE USER sample_user IDENTIFIED BY sample_password;
GRANT CONNECT, RESOURCE, CREATE TABLE, CREATE SEQUENCE TO sample_user;
ALTER USER sample_user DEFAULT TABLESPACE sample_ts QUOTA UNLIMITED ON sample_ts;

-- Connect as sample_user and create schema
-- Note: In actual Oracle setup, you would run this as the sample_user
-- For now, we'll create in the default XE schema

-- Departments table
CREATE TABLE departments (
    department_id NUMBER PRIMARY KEY,
    department_name VARCHAR2(100) NOT NULL UNIQUE,
    manager_id NUMBER,
    location VARCHAR2(100),
    created_at DATE DEFAULT SYSDATE
);

-- Employees table
CREATE TABLE employees (
    employee_id NUMBER PRIMARY KEY,
    first_name VARCHAR2(100) NOT NULL,
    last_name VARCHAR2(100) NOT NULL,
    email VARCHAR2(100) UNIQUE,
    department_id NUMBER REFERENCES departments(department_id),
    salary NUMBER(10, 2),
    hire_date DATE,
    is_active CHAR(1) DEFAULT 'Y',
    created_at DATE DEFAULT SYSDATE
);

-- Add self-referencing foreign key to departments
ALTER TABLE departments ADD CONSTRAINT fk_departments_manager 
    FOREIGN KEY (manager_id) REFERENCES employees(employee_id);

-- Projects table
CREATE TABLE projects (
    project_id NUMBER PRIMARY KEY,
    project_name VARCHAR2(150) NOT NULL,
    description CLOB,
    start_date DATE NOT NULL,
    end_date DATE,
    budget NUMBER(15, 2),
    department_id NUMBER NOT NULL REFERENCES departments(department_id),
    status VARCHAR2(50) DEFAULT 'ACTIVE'
);

-- Project assignments (many-to-many)
CREATE TABLE project_assignments (
    assignment_id NUMBER PRIMARY KEY,
    project_id NUMBER NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    employee_id NUMBER NOT NULL REFERENCES employees(employee_id) ON DELETE CASCADE,
    role VARCHAR2(100),
    allocation_percentage NUMBER(5, 2),
    assigned_date DATE DEFAULT TRUNC(SYSDATE),
    UNIQUE (project_id, employee_id)
);

-- Create sequences for auto-increment
CREATE SEQUENCE departments_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE employees_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE projects_seq START WITH 1 INCREMENT BY 1;
CREATE SEQUENCE assignments_seq START WITH 1 INCREMENT BY 1;

-- Create indexes
CREATE INDEX idx_employees_department ON employees(department_id);
CREATE INDEX idx_employees_email ON employees(email);
CREATE INDEX idx_projects_department ON projects(department_id);
CREATE INDEX idx_assignments_project ON project_assignments(project_id);
CREATE INDEX idx_assignments_employee ON project_assignments(employee_id);

-- Insert sample data
INSERT INTO departments (department_id, department_name, location) 
VALUES (departments_seq.NEXTVAL, 'Engineering', 'Building A');
INSERT INTO departments (department_id, department_name, location) 
VALUES (departments_seq.NEXTVAL, 'Sales', 'Building B');
INSERT INTO departments (department_id, department_name, location) 
VALUES (departments_seq.NEXTVAL, 'Operations', 'Building C');

INSERT INTO employees (employee_id, first_name, last_name, email, department_id, salary, hire_date)
VALUES (employees_seq.NEXTVAL, 'John', 'Smith', 'john.smith@example.com', 1, 85000.00, TO_DATE('2020-01-15', 'YYYY-MM-DD'));
INSERT INTO employees (employee_id, first_name, last_name, email, department_id, salary, hire_date)
VALUES (employees_seq.NEXTVAL, 'Jane', 'Doe', 'jane.doe@example.com', 1, 90000.00, TO_DATE('2019-03-20', 'YYYY-MM-DD'));
INSERT INTO employees (employee_id, first_name, last_name, email, department_id, salary, hire_date)
VALUES (employees_seq.NEXTVAL, 'Bob', 'Johnson', 'bob.johnson@example.com', 2, 75000.00, TO_DATE('2021-06-10', 'YYYY-MM-DD'));
INSERT INTO employees (employee_id, first_name, last_name, email, department_id, salary, hire_date)
VALUES (employees_seq.NEXTVAL, 'Alice', 'Williams', 'alice.williams@example.com', 3, 80000.00, TO_DATE('2020-09-05', 'YYYY-MM-DD'));

INSERT INTO projects (project_id, project_name, description, start_date, end_date, budget, department_id, status)
VALUES (projects_seq.NEXTVAL, 'Migration Platform', 'Database migration system', TO_DATE('2024-01-01', 'YYYY-MM-DD'), TO_DATE('2024-12-31', 'YYYY-MM-DD'), 500000.00, 1, 'ACTIVE');
INSERT INTO projects (project_id, project_name, description, start_date, end_date, budget, department_id, status)
VALUES (projects_seq.NEXTVAL, 'Cloud Initiative', 'Move to cloud infrastructure', TO_DATE('2024-02-01', 'YYYY-MM-DD'), TO_DATE('2024-11-30', 'YYYY-MM-DD'), 750000.00, 3, 'ACTIVE');
INSERT INTO projects (project_id, project_name, description, start_date, end_date, budget, department_id, status)
VALUES (projects_seq.NEXTVAL, 'Analytics Dashboard', 'Business intelligence system', TO_DATE('2024-03-01', 'YYYY-MM-DD'), TO_DATE('2024-10-31', 'YYYY-MM-DD'), 200000.00, 1, 'PLANNING');

INSERT INTO project_assignments (assignment_id, project_id, employee_id, role, allocation_percentage)
VALUES (assignments_seq.NEXTVAL, 1, 1, 'Tech Lead', 80.00);
INSERT INTO project_assignments (assignment_id, project_id, employee_id, role, allocation_percentage)
VALUES (assignments_seq.NEXTVAL, 1, 2, 'Developer', 100.00);
INSERT INTO project_assignments (assignment_id, project_id, employee_id, role, allocation_percentage)
VALUES (assignments_seq.NEXTVAL, 2, 3, 'Project Manager', 50.00);
INSERT INTO project_assignments (assignment_id, project_id, employee_id, role, allocation_percentage)
VALUES (assignments_seq.NEXTVAL, 2, 4, 'Operations', 75.00);
INSERT INTO project_assignments (assignment_id, project_id, employee_id, role, allocation_percentage)
VALUES (assignments_seq.NEXTVAL, 3, 2, 'Analyst', 60.00);

-- Commit all changes
COMMIT;
