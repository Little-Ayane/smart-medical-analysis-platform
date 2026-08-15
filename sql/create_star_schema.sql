USE medical_db;

-- 医院维度
CREATE TABLE IF NOT EXISTS dim_hospital (
    hospital_id INT AUTO_INCREMENT PRIMARY KEY,
    permanent_facility_id INT,
    facility_name VARCHAR(255),
    operating_certificate_number VARCHAR(50),
    hospital_service_area VARCHAR(100),
    hospital_county VARCHAR(100),
    UNIQUE KEY uk_facility (permanent_facility_id)
);
INSERT IGNORE INTO dim_hospital (permanent_facility_id, facility_name, operating_certificate_number, hospital_service_area, hospital_county)
SELECT DISTINCT Permanent_Facility_Id, Facility_Name, Operating_Certificate_Number, Hospital_Service_Area, Hospital_County FROM medical_data;

-- 患者维度
CREATE TABLE IF NOT EXISTS dim_patient (
    patient_demo_id INT AUTO_INCREMENT PRIMARY KEY,
    age_group VARCHAR(50), gender CHAR(1), race VARCHAR(100), ethnicity VARCHAR(100), zip_code_3digits VARCHAR(10),
    UNIQUE KEY uk_patient (age_group, gender, race, ethnicity, zip_code_3digits)
);
INSERT IGNORE INTO dim_patient (age_group, gender, race, ethnicity, zip_code_3digits)
SELECT DISTINCT Age_Group, Gender, Race, Ethnicity, Zip_Code_3digits FROM medical_data;

-- 诊断维度
CREATE TABLE IF NOT EXISTS dim_diagnosis (
    diagnosis_id INT AUTO_INCREMENT PRIMARY KEY,
    ccsr_diagnosis_code VARCHAR(20),
    ccsr_diagnosis_description VARCHAR(500),
    UNIQUE KEY uk_diag (ccsr_diagnosis_code)
);
INSERT IGNORE INTO dim_diagnosis (ccsr_diagnosis_code, ccsr_diagnosis_description)
SELECT DISTINCT CCSR_Diagnosis_Code, CCSR_Diagnosis_Description FROM medical_data;

-- 手术维度
CREATE TABLE IF NOT EXISTS dim_procedure (
    procedure_id INT AUTO_INCREMENT PRIMARY KEY,
    ccsr_procedure_code VARCHAR(20),
    ccsr_procedure_description VARCHAR(500),
    UNIQUE KEY uk_proc (ccsr_procedure_code)
);
INSERT IGNORE INTO dim_procedure (ccsr_procedure_code, ccsr_procedure_description)
SELECT DISTINCT NULLIF(CCSR_Procedure_Code,'nan'), NULLIF(CCSR_Procedure_Description,'nan') FROM medical_data WHERE CCSR_Procedure_Code != 'nan';

-- DRG维度
CREATE TABLE IF NOT EXISTS dim_drg (
    drg_id INT AUTO_INCREMENT PRIMARY KEY,
    apr_drg_code INT, apr_drg_description VARCHAR(500),
    apr_mdc_code INT, apr_mdc_description VARCHAR(500),
    apr_severity_code INT, apr_severity_description VARCHAR(100),
    apr_risk_of_mortality VARCHAR(50), apr_medical_surgical VARCHAR(50),
    UNIQUE KEY uk_drg (apr_drg_code, apr_severity_code)
);
INSERT IGNORE INTO dim_drg (apr_drg_code, apr_drg_description, apr_mdc_code, apr_mdc_description, apr_severity_code, apr_severity_description, apr_risk_of_mortality, apr_medical_surgical)
SELECT DISTINCT APR_DRG_Code, APR_DRG_Description, APR_MDC_Code, APR_MDC_Description, APR_Severity_of_Illness_Code, APR_Severity_of_Illness_Description, APR_Risk_of_Mortality, APR_Medical_Surgical_Description FROM medical_data;

-- 支付维度
CREATE TABLE IF NOT EXISTS dim_payment (
    payment_id INT AUTO_INCREMENT PRIMARY KEY,
    payment_typology_1 VARCHAR(100), payment_typology_2 VARCHAR(100), payment_typology_3 VARCHAR(100),
    UNIQUE KEY uk_pay (payment_typology_1, payment_typology_2, payment_typology_3)
);
INSERT IGNORE INTO dim_payment (payment_typology_1, payment_typology_2, payment_typology_3)
SELECT DISTINCT NULLIF(Payment_Typology_1,'nan'), NULLIF(Payment_Typology_2,'nan'), NULLIF(Payment_Typology_3,'nan') FROM medical_data;

-- 时间维度
CREATE TABLE IF NOT EXISTS dim_time (
    year_id INT AUTO_INCREMENT PRIMARY KEY,
    discharge_year INT,
    UNIQUE KEY uk_year (discharge_year)
);
INSERT IGNORE INTO dim_time (discharge_year) SELECT DISTINCT Discharge_Year FROM medical_data;

-- 事实表
CREATE TABLE IF NOT EXISTS fact_discharge (
    fact_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    hospital_id INT, patient_demo_id INT, diagnosis_id INT, procedure_id INT NULL,
    drg_id INT, payment_id INT, year_id INT,
    type_of_admission VARCHAR(100), patient_disposition VARCHAR(100), emergency_department_indicator CHAR(1),
    length_of_stay FLOAT, total_charges DECIMAL(12,2), total_costs DECIMAL(12,2), birth_weight FLOAT,
    FOREIGN KEY (hospital_id) REFERENCES dim_hospital(hospital_id),
    FOREIGN KEY (patient_demo_id) REFERENCES dim_patient(patient_demo_id),
    FOREIGN KEY (diagnosis_id) REFERENCES dim_diagnosis(diagnosis_id),
    FOREIGN KEY (procedure_id) REFERENCES dim_procedure(procedure_id),
    FOREIGN KEY (drg_id) REFERENCES dim_drg(drg_id),
    FOREIGN KEY (payment_id) REFERENCES dim_payment(payment_id),
    FOREIGN KEY (year_id) REFERENCES dim_time(year_id),
    INDEX idx_diagnosis (diagnosis_id), INDEX idx_hospital (hospital_id), INDEX idx_year (year_id)
);

-- 插入事实数据
INSERT INTO fact_discharge
SELECT NULL,
    h.hospital_id, p.patient_demo_id, d.diagnosis_id, pr.procedure_id,
    drg.drg_id, pay.payment_id, t.year_id,
    m.Type_of_Admission, m.Patient_Disposition, m.Emergency_Department_Indicator,
    m.Length_of_Stay, m.Total_Charges, m.Total_Costs, m.Birth_Weight
FROM medical_data m
LEFT JOIN dim_hospital h ON m.Permanent_Facility_Id = h.permanent_facility_id
LEFT JOIN dim_patient p ON m.Age_Group=p.age_group AND m.Gender=p.gender AND m.Race=p.race AND m.Ethnicity=p.ethnicity AND m.Zip_Code_3digits=p.zip_code_3digits
LEFT JOIN dim_diagnosis d ON m.CCSR_Diagnosis_Code = d.ccsr_diagnosis_code
LEFT JOIN dim_procedure pr ON NULLIF(m.CCSR_Procedure_Code,'nan') = pr.ccsr_procedure_code
LEFT JOIN dim_drg drg ON m.APR_DRG_Code=drg.apr_drg_code AND m.APR_Severity_of_Illness_Code=drg.apr_severity_code
LEFT JOIN dim_payment pay ON NULLIF(m.Payment_Typology_1,'nan')=pay.payment_typology_1 AND NULLIF(m.Payment_Typology_2,'nan')=pay.payment_typology_2 AND NULLIF(m.Payment_Typology_3,'nan')=pay.payment_typology_3
LEFT JOIN dim_time t ON m.Discharge_Year = t.discharge_year;