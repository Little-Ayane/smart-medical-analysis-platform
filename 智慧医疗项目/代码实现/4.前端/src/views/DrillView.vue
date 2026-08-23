<template>
  <div class="page">
    <div class="page-header">
      <button class="back-btn" @click="$router.push('/dashboard')">← 返回数据大屏</button>
      <h2>🔍 多维下钻分析</h2>
      <span></span>
    </div>
    <div class="page-body">
      <div class="drill-filters">
        <div class="filter-item">
          <label>📅 年份</label>
          <select v-model="filters.year">
            <option value="2024">2024</option>
            <option value="2023">2023</option>
            <option value="2022">2022</option>
          </select>
        </div>
        <div class="filter-item">
          <label>📍 服务区</label>
          <input type="text" v-model="filters.serviceArea" placeholder="输入服务区" />
        </div>
        <div class="filter-item">
          <label>🏥 县</label>
          <input type="text" v-model="filters.county" placeholder="输入县名" />
        </div>
        <div class="filter-item">
          <label>🏛️ 机构</label>
          <input type="text" v-model="filters.facility" placeholder="输入机构名称" />
        </div>
        <div class="filter-item">
          <label>📋 DRG</label>
          <input type="text" v-model="filters.drg" placeholder="输入DRG编码" />
        </div>
        <div class="filter-item">
          <label>👤 年龄</label>
          <input type="text" v-model="filters.age" placeholder="输入年龄段" />
        </div>
        <div class="filter-item">
          <label>⚥ 性别</label>
          <select v-model="filters.gender">
            <option value="">全部</option>
            <option value="男">男</option>
            <option value="女">女</option>
          </select>
        </div>
        <button class="query-btn" @click="handleQuery">🔍 查询</button>
      </div>

      <div class="drill-table">
        <table>
          <thead>
            <tr>
              <th>年份</th>
              <th>县</th>
              <th>机构</th>
              <th>DRG 分组</th>
              <th>住院人次</th>
              <th>平均费用</th>
              <th>平均成本</th>
              <th>平均住院日</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in tableData" :key="row.id">
              <td>{{ row.year }}</td>
              <td>{{ row.county }}</td>
              <td>{{ row.facility }}</td>
              <td>{{ row.drg }}</td>
              <td>{{ row.patients }}</td>
              <td>{{ row.avgCost }}</td>
              <td>{{ row.avgCost2 }}</td>
              <td>{{ row.avgStay }}</td>
            </tr>
          </tbody>
        </table>
        <div class="drill-note">💡 数据为模拟示例，查询后替换为真实数据</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import api from '@/api'
import { ref } from 'vue'

const filters = ref({
  year: '2024',
  serviceArea: '',
  county: '',
  facility: '',
  drg: '',
  age: '',
  gender: ''
})

const tableData = ref([
  { id: 1, year: '2024', county: '纽约县', facility: '医院A', drg: '呼吸系统疾病', patients: '3,245', avgCost: '¥12,340', avgCost2: '¥8,920', avgStay: '6.2' },
  { id: 2, year: '2024', county: '国王县', facility: '医院B', drg: '心血管疾病', patients: '2,890', avgCost: '¥18,560', avgCost2: '¥12,340', avgStay: '8.1' },
  { id: 3, year: '2024', county: '皇后县', facility: '医院C', drg: '消化系统疾病', patients: '2,560', avgCost: '¥9,870', avgCost2: '¥6,540', avgStay: '4.5' },
  { id: 4, year: '2024', county: '布朗克斯县', facility: '医院D', drg: '神经系统疾病', patients: '1,890', avgCost: '¥15,230', avgCost2: '¥10,110', avgStay: '7.3' }
])

const handleQuery = async () => {
  console.log('查询条件:', filters.value)
  try {
    const res = await api.getDimensionCombine(filters.value)
    // 假设后端返回的数据格式是 { columns: [...], rows: [[...], ...] }
    tableData.value = res.data.rows.map((row, idx) => ({
      id: idx + 1,
      year: row[0],
      county: row[1],
      facility: row[2],
      drg: row[3],
      patients: row[4],
      avgCost: row[5],
      avgCost2: row[6],
      avgStay: row[7]
    }))
  } catch (err) {
    console.error('查询失败:', err)
  }
}
</script>

<style scoped>
.page {
  padding: 20px 30px;
  min-height: 100vh;
  background: radial-gradient(ellipse at center, #0a2a5e 0%, #051633 50%, #020e2a 100%);
  color: #e3f2fd;
  font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
}
.page::before {
  content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background-image:
    radial-gradient(1px 1px at 10% 20%, #4fc3f7 50%, transparent),
    radial-gradient(1px 1px at 30% 80%, #4dd0e1 50%, transparent),
    radial-gradient(1px 1px at 60% 40%, #81d4fa 50%, transparent),
    radial-gradient(2px 2px at 80% 70%, #29b6f6 50%, transparent),
    radial-gradient(1px 1px at 45% 55%, #4fc3f7 50%, transparent);
  background-size: 600px 600px;
  opacity: 0.4;
}
.page-header {
  position: relative; z-index: 1;
  display: flex; justify-content: space-between; align-items: center;
  max-width: 1400px; margin: 0 auto 16px;
  padding: 0 0 12px;
  border-bottom: 1px solid rgba(64,196,255,0.2);
}
.page-header h2 {
  font-size: 26px; font-weight: bold;
  background: linear-gradient(180deg, #ffffff 0%, #4fc3f7 100%);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: 3px;
  text-shadow: 0 0 20px rgba(64,196,255,0.4);
}
.back-btn {
  background: rgba(0,229,255,0.12);
  border: 1px solid rgba(0,229,255,0.5);
  color: #00e5ff;
  padding: 8px 18px; border-radius: 4px;
  cursor: pointer; font-size: 13px;
  letter-spacing: 1px;
  transition: all 0.3s;
}
.back-btn:hover {
  background: rgba(0,229,255,0.25);
  box-shadow: 0 0 16px rgba(0,229,255,0.5);
}
.page-body {
  position: relative; z-index: 1;
  max-width: 1400px; margin: 0 auto;
  background: rgba(8, 24, 56, 0.55);
  border: 1px solid rgba(64,196,255,0.25);
  border-radius: 4px;
  padding: 20px 24px;
  box-shadow: inset 0 0 30px rgba(0,150,255,0.08);
}
.page-body::before, .page-body::after {
  content: ""; position: absolute; width: 14px; height: 14px;
  border-color: #00e5ff; border-style: solid; border-width: 0;
}
.page-body::before { top: 0; left: 0; border-top-width: 2px; border-left-width: 2px; }
.page-body::after  { bottom: 0; right: 0; border-bottom-width: 2px; border-right-width: 2px; }

.drill-filters {
  display: flex; flex-wrap: wrap; gap: 12px 16px; align-items: flex-end;
  margin-bottom: 18px;
  padding-bottom: 14px;
  border-bottom: 1px dashed rgba(64,196,255,0.15);
}
.filter-item { display: flex; flex-direction: column; gap: 4px; }
.filter-item label {
  font-size: 11px;
  color: #7da3d4;
  letter-spacing: 1px;
}
.filter-item select, .filter-item input {
  padding: 6px 12px;
  background: rgba(8, 24, 56, 0.6);
  border: 1px solid rgba(64,196,255,0.3);
  border-radius: 3px;
  font-size: 13px;
  color: #e3f2fd;
  min-width: 110px; height: 32px;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.filter-item select:focus, .filter-item input:focus {
  border-color: #00e5ff;
  box-shadow: 0 0 12px rgba(0,229,255,0.3);
}
.filter-item select option { background: #0a2a5e; color: #e3f2fd; }
.query-btn {
  padding: 6px 28px; height: 32px;
  background: rgba(0,229,255,0.15);
  color: #00e5ff;
  border: 1px solid rgba(0,229,255,0.6);
  border-radius: 3px;
  font-size: 13px; font-weight: bold;
  letter-spacing: 2px;
  cursor: pointer;
  transition: all 0.3s;
}
.query-btn:hover {
  background: rgba(0,229,255,0.3);
  box-shadow: 0 0 20px rgba(0,229,255,0.6);
}

.drill-table { overflow-x: auto; }
.drill-table table { width: 100%; border-collapse: collapse; font-size: 13px; }
.drill-table th {
  background: rgba(0,229,255,0.08);
  padding: 10px 12px; text-align: left;
  font-weight: bold;
  color: #00e5ff;
  letter-spacing: 1px;
  border-bottom: 1px solid rgba(0,229,255,0.3);
}
.drill-table td {
  padding: 8px 12px;
  border-bottom: 1px dashed rgba(64,196,255,0.1);
  color: #e3f2fd;
}
.drill-table tbody tr {
  transition: background 0.2s;
}
.drill-table tbody tr:hover {
  background: rgba(0,229,255,0.06);
}
.drill-note {
  margin-top: 14px;
  font-size: 12px;
  color: #7da3d4;
  text-align: center;
  letter-spacing: 1px;
}
</style>