// ============================================================
// 维度枚举值 → 中文显示映射
// 仅用于前端图表展示，不改后端 API 契约（后端仍返回英文值，供过滤/下钻使用）。
// 用法：import { GENDER, t } from '@/utils/labels'; t(GENDER, 'M') // '男'
// ============================================================

// 通用取词：命中映射返回中文；null/undefined 返回「未知」；未命中原样返回
export function t(map, v) {
  if (v == null || v === '') return '未知'
  return map[v] ?? v
}

export const GENDER = { M: '男', F: '女' }

export const AGE_GROUP = {
  '0 to 17': '0~17岁',
  '18 to 29': '18~29岁',
  '30 to 49': '30~49岁',
  '50 to 69': '50~69岁',
  '70 or Older': '70岁及以上',
}

// APR 严重程度
export const SEVERITY = {
  Minor: '轻度',
  Moderate: '中度',
  Major: '重度',
  Extreme: '极重度',
  Unknown: '未知',
  Undetermined: '未定',
}

// APR 死亡风险
export const RISK_MORTALITY = {
  Minor: '低危',
  Moderate: '中危',
  Major: '高危',
  Extreme: '极高危',
  Unknown: '未知',
  Undetermined: '未定',
}

export const MEDICAL_SURGICAL = {
  Medical: '内科',
  Surgical: '外科',
  'Not Applicable': '不适用',
}

export const PAYMENT = {
  Medicare: '联邦医保',
  Medicaid: '医疗补助',
  'Private Health Insurance': '商业保险',
  'Blue Cross/Blue Shield': '蓝十字蓝盾',
  'Managed Care, Unspecified': '管理式医疗',
  'Self-Pay': '自费',
  'Miscellaneous/Other': '其它',
  'Federal/State/Local/VA': '政府/军人',
  'Department of Corrections': '惩教',
}

export const RACE = {
  White: '白人',
  'Other Race': '其它种族',
  'Black/African American': '黑人/非裔',
  'Multi-racial': '多种族',
}

export const ADMISSION = {
  Emergency: '急诊',
  Elective: '择期',
  Newborn: '新生儿',
  Urgent: '紧急',
  Trauma: '创伤',
  'Not Available': '不可用',
}

export const DISPOSITION = {
  'Home or Self Care': '居家/自理',
  'Home w/ Home Health Services': '居家+健康服务',
  'Skilled Nursing Home': '专业护理院',
  Expired: '死亡',
  'Left Against Medical Advice': '非医嘱离院',
  'Short-term Hospital': '转短期医院',
  'Inpatient Rehabilitation Facility': '住院康复机构',
  'Hospice - Home': '临终关怀(居家)',
  'Psychiatric Hospital or Unit of Hosp': '精神科医院/病房',
  'Hospice - Medical Facility': '临终关怀(机构)',
  'Facility w/ Custodial/Supportive Care': '监护/支持护理',
  'Another Type Not Listed': '其它未列明',
  'Court/Law Enforcement': '法院/执法',
  'Medicare Cert Long Term Care Hospital': '长期护理医院',
  'Hosp Basd Medicare Approved Swing Bed': '轮转床位',
  "Cancer Center or Children's Hospital": '癌症中心/儿童医院',
  'Cancer Center or Childrens Hospital': '癌症中心/儿童医院',
  'Medicaid Cert Nursing Facility': '护理机构',
  'Federal Health Care Facility': '联邦医疗机构',
  'Critical Access Hospital': '关键通道医院',
  'Admitted from Ambulatory Surgery': '门诊手术转入',
}

export const EMERGENCY = { Y: '急诊', N: '非急诊' }

// 离院去向的分组短标签（quality/disposition 端点返回的分组键）
export const DISPOSITION_GROUP = {
  Home: '居家',
  'Transfer/Other Facility': '转院/其它机构',
  SNF: '专业护理院',
  Hospice: '临终关怀',
  Expired: '死亡',
  AMA: '非医嘱离院',
  Other: '其它',
}
