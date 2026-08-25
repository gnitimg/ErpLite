<script lang="ts" setup>
import type { FormInstance, FormRules } from "element-plus"
import { useUserStore } from "@/pinia/stores/user"

const userStore = useUserStore()

const formRef = ref<FormInstance>()

const loading = ref(false)

const form = reactive({
  oldPassword: "",
  newPassword: "",
  confirmPassword: ""
})

// visible 由 store 标志单向驱动；对话框配置为不可手动关闭，仅改密成功后 store 置 false 自动关闭。
const visible = computed({
  get: () => userStore.mustChangePassword,
  set: () => {}
})

function strengthOk(pw: string) {
  return pw.length >= 8 && /[a-zA-Z]/.test(pw) && /\d/.test(pw)
}

const rules: FormRules = {
  oldPassword: [{ required: true, message: "请输入原密码", trigger: "blur" }],
  newPassword: [
    { required: true, message: "请输入新密码", trigger: "blur" },
    {
      validator: (_rule, value: string, callback) =>
        strengthOk(value) ? callback() : callback(new Error("需 8 位以上且同时包含字母与数字")),
      trigger: "blur"
    }
  ],
  confirmPassword: [
    { required: true, message: "请再次输入新密码", trigger: "blur" },
    {
      validator: (_rule, value: string, callback) =>
        value === form.newPassword ? callback() : callback(new Error("两次输入的新密码不一致")),
      trigger: "blur"
    }
  ]
}

async function submit() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await userStore.changePassword(form.oldPassword, form.newPassword)
      ElMessage.success("密码修改成功")
      form.oldPassword = ""
      form.newPassword = ""
      form.confirmPassword = ""
    } catch {
      // 错误提示由 axios 拦截器统一处理
    } finally {
      loading.value = false
    }
  })
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="首次登录请修改密码"
    width="420px"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    :show-close="false"
    align-center
  >
    <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 16px">
      当前密码不满足安全强度要求，请设置新密码后继续使用系统。
    </el-alert>
    <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
      <el-form-item label="原密码" prop="oldPassword">
        <el-input v-model.trim="form.oldPassword" type="password" show-password />
      </el-form-item>
      <el-form-item label="新密码" prop="newPassword">
        <el-input v-model.trim="form.newPassword" type="password" show-password />
      </el-form-item>
      <el-form-item label="确认密码" prop="confirmPassword">
        <el-input v-model.trim="form.confirmPassword" type="password" show-password @keyup.enter="submit" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button type="primary" :loading="loading" @click="submit">提交新密码</el-button>
    </template>
  </el-dialog>
</template>
