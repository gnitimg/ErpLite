<script setup lang="ts">
import { printBrand, showBrandLogo, showBrandName } from "../print"
</script>

<template>
  <div v-if="showBrandLogo() || showBrandName()" class="print-brand">
    <img v-if="showBrandLogo()" :src="printBrand.logo" class="brand-logo" alt="厂标">
    <span v-if="showBrandName()" class="brand-name">{{ printBrand.company_name }}</span>
  </div>
</template>

<style scoped>
.print-brand { display: flex; align-items: center; gap: 10px; min-width: 0; overflow: hidden; }
.brand-logo { max-height: 52px; max-width: 100%; object-fit: contain; }
.brand-name { font-size: 22px; font-weight: 700; color: #000; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
</style>
