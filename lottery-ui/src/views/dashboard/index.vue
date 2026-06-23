<template>
  <div class="dashboard-container">
    <el-row :gutter="20">
      <!-- 双色球卡片 -->
      <el-col :xs="24" :sm="12" :md="8">
        <el-card shadow="hover" class="lottery-card">
          <template #header>
            <div class="card-header">
              <span>🟥 双色球最新一期</span>
              <el-button size="small" type="primary" plain @click="fetchLatestSSQ">刷新</el-button>
            </div>
          </template>
          <div v-if="latestSSQ" class="card-body">
            <div class="issue-row"><strong>期号：</strong>{{ latestSSQ.issue_num }}</div>
            <div class="ball-row">
              <span class="label">红球：</span>
              <el-tag
                v-for="i in 6"
                :key="i"
                size="small"
                type="danger"
                class="ball-tag"
              >
                {{ latestSSQ[`red_${['one','two','three','four','five','six'][i-1]}`] }}
              </el-tag>
            </div>
            <div class="ball-row">
              <span class="label">蓝球：</span>
              <el-tag size="small" type="primary" class="ball-tag">{{ latestSSQ.blue_one }}</el-tag>
            </div>
            <div class="stats-row">
              <span><strong>和值：</strong>{{ latestSSQ.red_summation }}</span>
              <span><strong>跨度：</strong>{{ latestSSQ.red_span }}</span>
            </div>
          </div>
          <div v-else class="empty-state">暂无数据</div>
        </el-card>
      </el-col>

      <!-- 大乐透卡片 -->
      <el-col :xs="24" :sm="12" :md="8">
        <el-card shadow="hover" class="lottery-card">
          <template #header>
            <div class="card-header">
              <span>🟦 大乐透最新一期</span>
              <el-button size="small" type="primary" plain @click="fetchLatestDLT">刷新</el-button>
            </div>
          </template>
          <div v-if="latestDLT" class="card-body">
            <div class="issue-row"><strong>期号：</strong>{{ latestDLT.issue_num }}</div>
            <div class="ball-row">
              <span class="label">前区：</span>
              <el-tag
                v-for="i in 5"
                :key="i"
                size="small"
                type="warning"
                class="ball-tag"
              >
                {{ latestDLT[`front_${['one','two','three','four','five'][i-1]}`] }}
              </el-tag>
            </div>
            <div class="ball-row">
              <span class="label">后区：</span>
              <el-tag
                v-for="i in 2"
                :key="i"
                size="small"
                type="success"
                class="ball-tag"
              >
                {{ latestDLT[`back_${['one','two'][i-1]}`] }}
              </el-tag>
            </div>
            <div class="stats-row">
              <span><strong>前区和值：</strong>{{ latestDLT.front_summation }}</span>
              <span><strong>跨度：</strong>{{ latestDLT.front_span }}</span>
            </div>
          </div>
          <div v-else class="empty-state">暂无数据</div>
        </el-card>
      </el-col>

      <!-- 模型列表卡片 -->
      <el-col :xs="24" :sm="24" :md="8">
        <el-card shadow="hover" class="lottery-card">
          <template #header>
            <div class="card-header">
              <span>🧠 已训练模型</span>
              <el-button size="small" type="primary" plain @click="fetchModels">刷新</el-button>
            </div>
          </template>
          <div v-if="models.length" class="model-list">
            <el-tag
              v-for="m in models"
              :key="m"
              size="default"
              class="model-tag"
              hit
            >
              <el-icon><Document /></el-icon> {{ m }}
            </el-tag>
          </div>
          <div v-else class="empty-state">暂无模型</div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
/**
 * 仪表盘页面
 * 显示最新开奖数据和已训练模型
 */
import { ref, onMounted } from 'vue'
import { getLatestSSQ, getLatestDLT } from '@/api/data'
import { listModels } from '@/api/model'
import { Document } from '@element-plus/icons-vue'

const latestSSQ = ref(null)
const latestDLT = ref(null)
const models = ref([])

const fetchLatestSSQ = async () => {
  latestSSQ.value = await getLatestSSQ()
}
const fetchLatestDLT = async () => {
  latestDLT.value = await getLatestDLT()
}
const fetchModels = async () => {
  const res = await listModels()
  models.value = res.models || []
}

onMounted(() => {
  fetchLatestSSQ()
  fetchLatestDLT()
  fetchModels()
})
</script>

<style scoped>
/* 响应式间距 */
.dashboard-container {
  padding: 20px;
}
@media (max-width: 768px) {
  .dashboard-container {
    padding: 10px;
  }
}

/* 卡片头部：标题和按钮左右分布 */
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

/* 卡片内部通用 */
.card-body {
  font-size: 14px;
  line-height: 1.8;
}
.issue-row {
  margin-bottom: 8px;
}
.ball-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 6px;
}
.ball-row .label {
  font-weight: 500;
  margin-right: 6px;
  min-width: 36px;
}
.ball-tag {
  margin: 2px 4px 2px 0;
}
.stats-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #ebeef5;
}
.empty-state {
  color: #909399;
  text-align: center;
  padding: 12px 0;
}

/* 模型列表：使用标签云 */
.model-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.model-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  cursor: default;
}
.model-tag .el-icon {
  font-size: 16px;
}

/* 移动端微调 */
@media (max-width: 768px) {
  .card-body {
    font-size: 13px;
  }
  .ball-tag {
    font-size: 12px;
    padding: 0 8px;
    height: 24px;
  }
  .stats-row {
    gap: 12px;
    font-size: 13px;
  }
}
</style>