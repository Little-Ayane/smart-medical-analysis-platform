import axios from 'axios'

const USE_MOCK = false
const API_BASE = '/api/v1'

const api = axios.create({
  baseURL: API_BASE,
  timeout: 120000,
  headers: { 'Content-Type': 'application/json' }
})

api.interceptors.response.use(
  res => res.data,
  err => {
    console.error('API 请求失败:', err)
    return Promise.reject(err)
  }
)

export default {
  // ====== 原有接口 ======
  getDrgCostRanking(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: { hospitals: ['县医院A', '县医院B', '县医院C', '县医院D', '县医院E'], costs: [8500, 7200, 6800, 6100, 5300] }
      })
    }
    return api.post('/drg/cost-ranking', params)
  },
  getDiseaseSpectrum(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: { diseases: ['呼吸系统', '消化系统', '心血管', '神经系统', '肿瘤', '骨科', '妇产科'], counts: [32000, 28000, 25000, 18000, 15000, 12000, 9000] }
      })
    }
    return api.post('/disease/spectrum', params)
  },
  getPaymentStructure(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: { categories: ['医保支付', '自费', '商业保险'], values: [67.3, 22.1, 10.6] }
      })
    }
    return api.post('/payment/structure', params)
  },
  getQualityData(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: { data: [[2.5,3.8], [3.2,4.1], [1.8,2.5], [4.0,4.5], [2.0,3.0], [3.5,3.9], [1.5,2.0], [4.2,4.8]] }
      })
    }
    return api.post('/quality/monitor', params)
  },
  getEmergencyData(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: { diseases: ['呼吸系统', '心血管', '消化系统', '神经系统', '骨科'], days: [6.2, 8.1, 4.5, 7.3, 5.8] }
      })
    }
    return api.post('/emergency/statistics', params)
  },
  getCostTrend(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: { months: ['1月', '2月', '3月', '4月', '5月', '6月'], costs: [1200, 1350, 1100, 1500, 1680, 1900] }
      })
    }
    return api.post('/cost/trend', params)
  },
  getStayComparison(params) {
    if (USE_MOCK) return Promise.resolve({ data: { days: [6.2, 8.1, 4.5, 7.3, 5.8] } })
    return api.post('/drg/stay-comparison', params)
  },
  getMortalityRisk(params) {
    if (USE_MOCK) return Promise.resolve({ data: { risk: [0.2, 0.3, 0.1, 0.25, 0.15] } })
    return api.post('/drg/mortality-risk', params)
  },
  getCmiRanking(params) {
    if (USE_MOCK) return Promise.resolve({ data: { cmi: [1.2, 1.1, 0.9, 0.8, 0.7] } })
    return api.post('/drg/cmi-ranking', params)
  },
  getOutlierDetection(params) {
    if (USE_MOCK) return Promise.resolve({ data: { outliers: [1, 0, 0, 1, 0] } })
    return api.post('/drg/outlier-detection', params)
  },
  getDimensionCombine(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: {
          columns: ['年份', '县', '机构', 'DRG分组', '住院人次', '平均费用', '平均成本', '平均住院日'],
          rows: [
            ['2024', '纽约县', '医院A', '呼吸系统', '3245', '¥12340', '¥8920', '6.2'],
            ['2024', '国王县', '医院B', '心血管', '2890', '¥18560', '¥12340', '8.1'],
            ['2024', '皇后县', '医院C', '消化系统', '2560', '¥9870', '¥6540', '4.5'],
            ['2024', '布朗克斯县', '医院D', '神经系统', '1890', '¥15230', '¥10110', '7.3']
          ]
        }
      })
    }
    return api.post('/analysis/dimension-combine', params)
  },
  getMetricSwitch(params) { return api.post('/analysis/metric-switch', params) },
  getDrillDown(params) { return api.post('/analysis/drill-down', params) },
  getTimeRollup(params) { return api.post('/analysis/time-rollup', params) },
  getPivot(params) { return api.post('/analysis/pivot', params) },
  getMetadata() { return api.get('/analysis/metadata') },

  // ====== 急诊与住院分析模块（5个接口） ======
  getEmergencyRate() {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { year: 2020, emergency_rate: 25.0 },
          { year: 2021, emergency_rate: 25.7 },
          { year: 2022, emergency_rate: 22.8 },
          { year: 2023, emergency_rate: 22.1 },
          { year: 2024, emergency_rate: 24.1 }
        ]
      })
    }
    return api.get('/analysis/emergency-rate')
  },
  getEmergencyCompare() {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { is_emergency: 'Y', case_count: 2091253, avg_los: 5.2, avg_charges: 18500.50 },
          { is_emergency: 'N', case_count: 1200000, avg_los: 3.1, avg_charges: 9200.00 }
        ]
      })
    }
    return api.get('/analysis/emergency-compare')
  },
  getAvgLos(params) {
    if (USE_MOCK) {
      const mockMap = {
        age_group: [{ key: '0-17', avg_los: 2.5 }, { key: '18-29', avg_los: 3.1 }, { key: '30-49', avg_los: 4.3 }, { key: '50-69', avg_los: 6.2 }, { key: '70+', avg_los: 8.7 }],
        gender: [{ key: 'M', avg_los: 4.8 }, { key: 'F', avg_los: 4.2 }],
        discharge_year: [{ key: 2020, avg_los: 5.1 }, { key: 2021, avg_los: 4.8 }, { key: 2022, avg_los: 4.5 }, { key: 2023, avg_los: 4.3 }, { key: 2024, avg_los: 4.0 }]
      }
      const groupBy = params?.group_by || 'age_group'
      return Promise.resolve({ data: mockMap[groupBy] || mockMap.age_group })
    }
    return api.get('/analysis/avg-los', { params })
  },
  getOutliers(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { facility_name: 'NYC Health + Hospitals', age_group: '70+', gender: 'M', length_of_stay: 120, total_charges: 1250000.50, patient_disposition: 'Skilled Nursing Home' },
          { facility_name: 'Mount Sinai Hospital', age_group: '50-69', gender: 'F', length_of_stay: 85, total_charges: 890000.00, patient_disposition: 'Home with Home Health Services' }
        ]
      })
    }
    return api.get('/analysis/outliers', { params })
  },
  getDispositionEmergencyCross() {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { is_emergency: 'Y', patient_disposition: 'Home', cnt: 350000 },
          { is_emergency: 'Y', patient_disposition: 'Skilled Nursing Home', cnt: 85000 },
          { is_emergency: 'Y', patient_disposition: 'Expired', cnt: 15000 },
          { is_emergency: 'N', patient_disposition: 'Home', cnt: 980000 },
          { is_emergency: 'N', patient_disposition: 'Skilled Nursing Home', cnt: 120000 },
          { is_emergency: 'N', patient_disposition: 'Expired', cnt: 8000 }
        ]
      })
    }
    return api.get('/analysis/disposition/emergency-cross')
  },

  // ====== 病种与手术分析模块（7个接口） ======
  getTopDiagnoses(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { code: 'PNL001', name: 'LIVEBORN', count: 154598, value: 154598 },
          { code: 'INF002', name: 'SEPTICEMIA', count: 138031, value: 138031 },
          { code: 'INF012', name: 'CORONAVIRUS DISEASE 2019 (COVID-19)', count: 82591, value: 82591 }
        ]
      })
    }
    return api.get('/disease/top-diagnoses', { params })
  },
  getTopProcedures(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { code: 'PGN002', name: 'SPONTANEOUS VAGINAL DELIVERY', count: 113319, value: 113319 },
          { code: 'PGN003', name: 'CESAREAN SECTION', count: 78234, value: 78234 }
        ]
      })
    }
    return api.get('/disease/top-procedures', { params })
  },
  getSeverityProfile(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { group: '0 to 17', severity: 'Minor', value: 135802 },
          { group: '0 to 17', severity: 'Moderate', value: 70471 },
          { group: '70 or Older', severity: 'Extreme', value: 120187 }
        ]
      })
    }
    return api.get('/disease/severity-profile', { params })
  },
  getPopulationDiff(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { key: 'F', count: 1119640, pct: 54.44, value: 1119640 },
          { key: 'M', count: 936983, pct: 45.56, value: 936983 }
        ]
      })
    }
    return api.get('/disease/population-diff', { params })
  },
  getPyramid(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { age_group: '0 to 17', male: 129502, female: 115576, total: 245078 },
          { age_group: '70 or Older', male: 279957, female: 339616, total: 619573 }
        ]
      })
    }
    return api.get('/disease/pyramid', { params })
  },
  getRegionDiff(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { key: 'New York City', count: 913496, value: 913496 },
          { key: 'Long Island', count: 331353, value: 331353 }
        ]
      })
    }
    return api.get('/disease/region-diff', { params })
  },
  getHeatmap(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { dim1: 'PNL001', dim1_name: 'LIVEBORN', dim2: '0 to 17', dim2_name: '0 to 17', value: 154598 }
        ]
      })
    }
    return api.get('/disease/heatmap', { params })
  },

  // ====== 大屏预聚合数据 ======
  getBigscreenOverview() {
    return api.get('/bigscreen/overview')
  },

  // ====== 支付分析模块（6个接口） ======
  getPaymentComposition(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { key: 'Medicare', count: 826128, pct: 40.17, value: 826128 },
          { key: 'Medicaid', count: 407960, pct: 19.84, value: 407960 },
          { key: 'Private Health Insurance', count: 356040, pct: 17.31, value: 356040 },
          { key: 'Self-Pay', count: 153374, pct: 7.46, value: 153374 }
        ]
      })
    }
    return api.get('/payment/composition', { params })
  },
  getPaymentCross(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { key: 'Medicare', dim2: '70 or Older', dim2_name: '70 or Older', value: 524788 },
          { key: 'Medicare', dim2: '50 to 69', dim2_name: '50 to 69', value: 301340 }
        ]
      })
    }
    return api.get('/payment/cross', { params })
  },
  getPaymentSankey(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: {
          nodes: [
            { name: '支付1|Medicare', display: 'Medicare', layer: '支付1', layer_index: 0 },
            { name: '支付1|Medicaid', display: 'Medicaid', layer: '支付1', layer_index: 0 },
            { name: '支付2|Medicaid', display: 'Medicaid', layer: '支付2', layer_index: 1 },
            { name: '支付2|Self-Pay', display: 'Self-Pay', layer: '支付2', layer_index: 1 }
          ],
          links: [
            { source: '支付1|Medicare', target: '支付2|Medicaid', value: 201825 },
            { source: '支付1|Medicaid', target: '支付2|Medicaid', value: 201660 },
            { source: '支付1|Medicare', target: '支付2|Self-Pay', value: 110854 }
          ]
        }
      })
    }
    return api.get('/payment/sankey', { params })
  },
  getPaymentCostRelation(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { key: 'Medicare', count: 826128, avg_charges: 87986.26, avg_costs: 25755.28, charge_cost_ratio: 3.42 },
          { key: 'Medicaid', count: 407960, avg_charges: 69120.50, avg_costs: 20110.20, charge_cost_ratio: 3.44 },
          { key: 'Self-Pay', count: 153374, avg_charges: 52100.80, avg_costs: 15620.30, charge_cost_ratio: 3.34 }
        ]
      })
    }
    return api.get('/payment/cost-relation', { params })
  },
  getPaymentOopBurden(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { key: '30 to 49', total_count: 415627, self_pay_count: 7218, self_pay_pct: 1.74, self_pay_avg_charges: 48910.04 },
          { key: '70 or Older', total_count: 619573, self_pay_count: 6180, self_pay_pct: 1.00, self_pay_avg_charges: 53200.20 },
          { key: '50 to 69', total_count: 512340, self_pay_count: 5520, self_pay_pct: 1.08, self_pay_avg_charges: 50110.30 }
        ]
      })
    }
    return api.get('/payment/oop-burden', { params })
  },
  getPaymentSummary(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: {
          total_records: 2056774,
          total_charges: 153555627951.47,
          total_costs: 46095406196.02,
          avg_charges: 74658.48,
          avg_costs: 22411.51,
          avg_los: 5.83,
          self_pay_count: 26310,
          self_pay_pct: 1.28,
          top_payment: { key: 'Medicare', count: 826128, pct: 40.17 },
          severity_distribution: { Minor: 598786, Moderate: 755709, Major: 498975, Extreme: 200761, Unknown: 2543 },
          ed_count: 1316133
        }
      })
    }
    return api.get('/payment/summary', { params })
  },

  // ====== 医疗质量监测模块（5个接口） ======
  getQualityOverview(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: {
          total_records: 2056774,
          deaths: 43180,
          mortality_rate: 2.10,
          avg_los: 5.83,
          ed_count: 1316133,
          ed_rate: 63.99,
          ama_count: 21050,
          ama_rate: 1.02,
          transfer_count: 180520,
          transfer_rate: 8.78,
          newborns: 245078,
          lbw_count: 1985,
          lbw_rate: 0.81,
          avg_charges: 74658.48,
          avg_costs: 22411.51
        }
      })
    }
    return api.get('/quality/overview', { params })
  },
  getQualityMortality(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { key: 'INF002', name: 'SEPTICEMIA', count: 138031, deaths: 9510, mortality_rate: 6.89 },
          { key: 'RSP004', name: 'RESPIRATORY FAILURE', count: 43210, deaths: 2970, mortality_rate: 6.87 },
          { key: 'CIR010', name: 'CARDIAC ARREST', count: 15230, deaths: 998, mortality_rate: 6.55 }
        ]
      })
    }
    return api.get('/quality/mortality', { params })
  },
  getQualityLos(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { key: '70 or Older', name: '70 or Older', count: 619573, avg_los: 7.12, avg_charges: 92103.40, avg_costs: 28540.12 },
          { key: '50 to 69', name: '50 to 69', count: 512340, avg_los: 5.98, avg_charges: 78120.55, avg_costs: 23610.77 },
          { key: '30 to 49', name: '30 to 49', count: 415627, avg_los: 4.51, avg_charges: 61203.18, avg_costs: 17890.03 }
        ]
      })
    }
    return api.get('/quality/length-of-stay', { params })
  },
  getQualityFacilityRanking(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { key: 'Strong Memorial Hospital', name: 'Strong Memorial Hospital', county: 'Monroe', count: 12030, deaths: 410, mortality_rate: 3.41, avg_los: 5.20, ed_rate: 71.30, ama_rate: 0.30, transfer_rate: 2.10, newborns: 2010, lbw_rate: 1.20, avg_charges: 81205.60, avg_costs: 24310.22 },
          { key: 'Unknown', name: 'Unknown', county: null, count: 12089, deaths: 330, mortality_rate: 2.73, avg_los: 4.90, ed_rate: 60.10, ama_rate: 0.25, transfer_rate: 1.80, newborns: 1500, lbw_rate: 0.90, avg_charges: 71002.35, avg_costs: 20980.40 }
        ]
      })
    }
    return api.get('/quality/facility-ranking', { params })
  },
  getQualityDisposition(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { key: 'Home', count: 1520010, pct: 73.90 },
          { key: 'Transfer/Other Facility', count: 180520, pct: 8.78 },
          { key: 'SNF', count: 140010, pct: 6.81 },
          { key: 'Hospice', count: 60120, pct: 2.92 },
          { key: 'Expired', count: 43180, pct: 2.10 },
          { key: 'AMA', count: 21050, pct: 1.02 },
          { key: 'Other', count: 91884, pct: 4.47 }
        ]
      })
    }
    return api.get('/quality/disposition', { params })
  },

  // ====== DRG分析模块（6个接口） ======
  getDrgCostRankingApi(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: {
          rows: [
            { drg_code: 560, drg_desc: 'NEONATE BIRTH WEIGHT > 2499 GRAMS', mdc_code: 15, mdc_desc: 'NEWBORN AND OTHER NEONATES', cases: 139203, total_charges: 1900707161.33, avg_charges: 13654.21 },
            { drg_code: 470, drg_desc: 'MAJOR JOINT REPLACEMENT', mdc_code: 8, mdc_desc: 'MUSCULOSKELETAL', cases: 98234, total_charges: 1823456789.50, avg_charges: 18562.34 },
            { drg_code: 871, drg_desc: 'SEPTICEMIA', mdc_code: 18, mdc_desc: 'INFECTIOUS DISEASES', cases: 87521, total_charges: 1567234567.20, avg_charges: 17908.76 }
          ]
        }
      })
    }
    return api.post('/drg/cost-ranking', params)
  },
  getDrgStayComparison(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: {
          rows: [
            { drg_code: 560, drg_desc: 'NEONATE BIRTH WEIGHT > 2499 GRAMS', avg_stay: 2.3, cases: 139203 },
            { drg_code: 470, drg_desc: 'MAJOR JOINT REPLACEMENT', avg_stay: 4.8, cases: 98234 },
            { drg_code: 871, drg_desc: 'SEPTICEMIA', avg_stay: 7.2, cases: 87521 }
          ]
        }
      })
    }
    return api.post('/drg/stay-comparison', params)
  },
  getDrgMortalityRisk(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: {
          rows: [
            { risk_mortality: 'Minor', cases: 987564, percentage: 48.86, avg_charges: 44536.80, avg_stay: 3.64 },
            { risk_mortality: 'Moderate', cases: 543210, percentage: 26.88, avg_charges: 68234.50, avg_stay: 5.21 },
            { risk_mortality: 'Major', cases: 248660, percentage: 12.30, avg_charges: 102345.20, avg_stay: 7.89 },
            { risk_mortality: 'Extreme', cases: 241819, percentage: 11.96, avg_charges: 152077.34, avg_stay: 10.59 }
          ]
        }
      })
    }
    return api.post('/drg/mortality-risk', params)
  },
  getDrgCmiRanking(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: {
          rows: [
            { drg_code: 2, drg_desc: 'HEART TRANSPLANT', cases: 150, avg_charges: 500000.00, cmi: 6.73 },
            { drg_code: 5, drg_desc: 'LIVER TRANSPLANT', cases: 120, avg_charges: 450000.00, cmi: 6.05 },
            { drg_code: 10, drg_desc: 'PANCREAS TRANSPLANT', cases: 80, avg_charges: 380000.00, cmi: 5.11 }
          ]
        }
      })
    }
    return api.post('/drg/cmi-ranking', params)
  },
  getDrgOutlierDetection(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: {
          method: 'iqr',
          threshold: 1.5,
          metric: 'avg_charges',
          outliers: [
            { drg_code: 2, drg_desc: 'HEART TRANSPLANT', cases: 150, avg_charges: 500000.00, outlier_type: 'high', deviation: 425690.35 },
            { drg_code: 5, drg_desc: 'LIVER TRANSPLANT', cases: 120, avg_charges: 450000.00, outlier_type: 'high', deviation: 375690.35 }
          ],
          outlier_count: 25,
          normal_count: 301
        }
      })
    }
    return api.post('/drg/outlier-detection', params)
  },
  getDrgSummary(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: {
          total_drg: 326,
          total_cases: 2021253,
          total_charges: 150198609334.49,
          avg_stay: 5.71
        }
      })
    }
    return api.get('/drg/summary', { params })
  },

  // ====== 费用成本分析模块（5个接口） ======
  getCostProfitDifference(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { key: 'SEPTICEMIA', count: 138031, value: 52345678.50, total_charges: 72345678.50, total_costs: 20000000.00, avg_charges: 52412.34, avg_costs: 14489.56, avg_profit_difference: 37922.78 },
          { key: 'RESPIRATORY FAILURE', count: 43210, value: 18345678.20, total_charges: 26345678.20, total_costs: 8000000.00, avg_charges: 60978.12, avg_costs: 18514.23, avg_profit_difference: 42463.89 },
          { key: 'MAJOR JOINT REPLACEMENT', count: 98234, value: 12345678.90, total_charges: 20345678.90, total_costs: 8000000.00, avg_charges: 20715.67, avg_costs: 8143.89, avg_profit_difference: 12571.78 }
        ]
      })
    }
    return api.get('/cost/profit-difference', { params })
  },
  getCostProfitMargin(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { key: 'MAJOR JOINT REPLACEMENT', count: 98234, value: 25.50, total_charges: 20345678.90, total_costs: 8000000.00, profit_margin_pct: 25.50, avg_charges: 20715.67, avg_costs: 8143.89, avg_profit_difference: 12571.78 },
          { key: 'SEPTICEMIA', count: 138031, value: 18.30, total_charges: 72345678.50, total_costs: 20000000.00, profit_margin_pct: 18.30, avg_charges: 52412.34, avg_costs: 14489.56, avg_profit_difference: 37922.78 }
        ]
      })
    }
    return api.get('/cost/profit-margin', { params })
  },
  getCostEfficiencyRanking(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { key: 'MAJOR JOINT REPLACEMENT', count: 98234, value: 25.50, efficiency_grade: 'A（高效益）', grade_basis: '利润率 25.50%' },
          { key: 'SEPTICEMIA', count: 138031, value: 18.30, efficiency_grade: 'B（中高效益）', grade_basis: '利润率 18.30%' }
        ]
      })
    }
    return api.get('/cost/efficiency-ranking', { params })
  },
  getCostComposition(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { key: 'MDC 1 - Nervous System', count: 85234, value: 18.50, total_charges: 52345678.50, avg_charges: 61412.34, pct: 18.50 },
          { key: 'MDC 5 - Circulatory System', count: 72341, value: 15.20, total_charges: 42345678.20, avg_charges: 58512.78, pct: 15.20 },
          { key: 'MDC 8 - Musculoskeletal', count: 98234, value: 12.80, total_charges: 35345678.90, avg_charges: 35978.12, pct: 12.80 }
        ],
        meta: { total_charges_all: 523456789.00 }
      })
    }
    return api.get('/cost/composition', { params })
  },
  getCostTrendApi(params) {
    if (USE_MOCK) {
      return Promise.resolve({
        data: [
          { year: 2020, value: 123456789.50, count: 450000, total_charges: 123456789.50, total_costs: 45678912.30, profit_difference: 77777877.20, profit_margin_pct: 17.00, avg_charges: 27434.89, avg_costs: 10150.87 },
          { year: 2021, value: 150198609.33, count: 510000, total_charges: 150198609.33, total_costs: 52345678.12, profit_difference: 97852931.21, profit_margin_pct: 18.70, avg_charges: 29450.71, avg_costs: 10263.86 },
          { year: 2022, value: 134567890.45, count: 490000, total_charges: 134567890.45, total_costs: 48901234.56, profit_difference: 85666655.89, profit_margin_pct: 17.50, avg_charges: 27462.83, avg_costs: 9979.84 }
        ]
      })
    }
    return api.get('/cost/trend', { params })
  }
}