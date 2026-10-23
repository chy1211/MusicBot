<script setup lang="ts">
import Preferences from './components/Preferences.vue'
import LoginScreen from './components/LoginScreen.vue'
import {useDashboard} from './composables/useDashboard'
useDashboard()
</script>
<template><Preferences/><LoginScreen/><RouterView/></template>
