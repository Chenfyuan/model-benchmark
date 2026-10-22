<script setup lang="ts">
import { message } from 'ant-design-vue'
import { computed, onMounted, reactive, ref } from 'vue'
import { api, type BudgetLimits, type BudgetView } from '../api'
import PageHeader from '../components/PageHeader.vue'
import { fmtCost, fmtTokens } from '../format'

const view = ref<BudgetView | null>(null)
const saving = ref(false)
const form = reactive<BudgetLimits>({ per_run_max_tokens: null, per_run_max_cost: null, monthly_max_tokens: null, monthly_max_cost: null })

function apply(v: BudgetView) { view.value = v; Object.assign(form, v.limits) }
onMounted(async () => apply(await api.budget()))

async function save() {
  saving.value = true
  try { apply(await api.saveBudget({ ...form })); message.success('已保存') } finally { saving.value = false }
}
const anyLimit = computed(() => Object.values(form).some((v) => v != null && v !== 0))
const pct = (used: number, limit: number | null) => (limit ? Math.min(100, Math.round((used / limit) * 100)) : 0)
const status = (used: number, limit: number | null) => (limit && used > limit ? 'exception' : 'normal')
</script>

<template>
  <div class="page" style="max-width: 880px">
    <PageHeader title="费用限额" sub="默认不限制。设了上限之后，超出的评测会被拦截或自动停止。" />

    <div v-if="view" class="card card-pad" style="margin-bottom: 16px">
      <div class="row-between"><h3 class="section-title">本月用量</h3><span class="faint">{{ view.usage.month }}（UTC 自然月）</span></div>
      <div class="grid grid-4" style="margin: 12px 0">
        <div><div class="muted">累计 token</div><div class="n">{{ fmtTokens(view.usage.tokens) }}</div></div>
        <div><div class="muted">累计费用</div><div class="n">{{ fmtCost(view.usage.cost) }}</div></div>
        <div><div class="muted">评测任务数</div><div class="n">{{ view.usage.runs }}</div></div>
      </div>
      <template v-if="view.limits.monthly_max_tokens">
        <div class="muted" style="font-size: 13px">月度 token：{{ fmtTokens(view.usage.tokens) }} / {{ fmtTokens(view.limits.monthly_max_tokens) }}</div>
        <a-progress :percent="pct(view.usage.tokens, view.limits.monthly_max_tokens)" :status="status(view.usage.tokens, view.limits.monthly_max_tokens)" />
      </template>
      <template v-if="view.limits.monthly_max_cost">
        <div class="muted" style="font-size: 13px">月度费用：{{ fmtCost(view.usage.cost) }} / {{ fmtCost(view.limits.monthly_max_cost) }}</div>
        <a-progress :percent="pct(view.usage.cost, view.limits.monthly_max_cost)" :status="status(view.usage.cost, view.limits.monthly_max_cost)" />
      </template>
      <div v-if="!view.limits.monthly_max_tokens && !view.limits.monthly_max_cost" class="faint" style="font-size: 13px">没有设置月度上限。</div>
    </div>

    <div class="card card-pad">
      <h3 class="section-title">上限设置</h3>
      <p class="section-sub">留空表示不限制。token 数一定能统计；金额只对填了单价的模型生效。</p>
      <a-form layout="vertical" :model="form">
        <div class="grid" style="grid-template-columns: 1fr 1fr">
          <a-form-item label="单次评测 · token 上限" name="per_run_max_tokens"><a-input-number v-model:value="form.per_run_max_tokens" :min="0" :controls="false" placeholder="不限制" style="width: 100%"><template #addonAfter>token</template></a-input-number></a-form-item>
          <a-form-item label="单次评测 · 金额上限" name="per_run_max_cost"><a-input-number v-model:value="form.per_run_max_cost" :min="0" :controls="false" placeholder="不限制" style="width: 100%"><template #addonAfter>金额</template></a-input-number></a-form-item>
          <a-form-item label="每月 · token 上限" name="monthly_max_tokens"><a-input-number v-model:value="form.monthly_max_tokens" :min="0" :controls="false" placeholder="不限制" style="width: 100%"><template #addonAfter>token</template></a-input-number></a-form-item>
          <a-form-item label="每月 · 金额上限" name="monthly_max_cost"><a-input-number v-model:value="form.monthly_max_cost" :min="0" :controls="false" placeholder="不限制" style="width: 100%"><template #addonAfter>金额</template></a-input-number></a-form-item>
        </div>
      </a-form>
      <a-alert v-if="view?.unpriced_models.length && (form.per_run_max_cost || form.monthly_max_cost)" type="warning" show-icon style="margin-bottom: 14px"
        :message="`这些模型没有填写单价，金额上限对它们不生效：${view.unpriced_models.join('、')}`" description="去“模型管理”里编辑模型，填上每百万 token 的单价；也可以只用 token 上限。" />
      <a-button type="primary" :loading="saving" @click="save">保存</a-button>
      <span v-if="!anyLimit" class="faint" style="margin-left: 12px">当前不限制</span>
    </div>

    <div class="card card-pad" style="margin-top: 16px">
      <h3 class="section-title">上限怎么起作用</h3>
      <ol class="muted" style="margin: 8px 0 0; padding-left: 20px; line-height: 1.9">
        <li><b>提交时</b>：按预估用量检查。预计超出会弹窗让你确认，确认后才会创建任务（内置基准的题数要首次运行后才知道，这一步查不了）。</li>
        <li><b>运行中</b>：按实际用量检查（每秒读取引擎已经写出的结果）。超出就自动停止，任务标记为失败并注明原因。</li>
        <li><b>已完成的样本不会白花</b>：停止时已经答完的样本会保留，调高上限后点“重试”只补跑剩下的，已完成的不会重复计费。例外：停止那一刻正在进行的请求（最多和并发数一样多）已经发给模型但没有结果，重试时会重发，所以实际花费可能比页面上的用量多出这几次。</li>
        <li><b>没有登录</b>：任何人都能改这里的上限和点“仍然提交”，所以它能防误操作，防不了有意绕过。</li>
      </ol>
    </div>
  </div>
</template>

<style scoped>
.n { font-size: 28px; font-weight: 650; letter-spacing: -0.02em; margin-top: 2px; font-variant-numeric: tabular-nums; }
</style>
