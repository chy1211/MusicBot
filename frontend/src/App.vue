<script setup lang="ts">
import {usePwa} from './composables/usePwa'
import Preferences from './components/Preferences.vue'
import LoginScreen from './components/LoginScreen.vue'
import {useDashboard} from './composables/useDashboard'
useDashboard();usePwa()
</script>
<template><Preferences/><LoginScreen/><RouterView/></template>
