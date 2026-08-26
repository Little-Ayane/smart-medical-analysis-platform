import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import DashboardView from '../views/DashboardView.vue'

const routes = [
  {
    path: '/',
    name: 'home',
    component: HomeView
  },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: DashboardView
  },
  {
    path: '/disease',
    name: 'disease',
    component: () => import('../views/DiseaseView.vue')
  },
  {
    path: '/payment',
    name: 'payment',
    component: () => import('../views/PaymentView.vue')
  },
  {
    path: '/hospital',
    name: 'hospital',
    component: () => import('../views/HospitalView.vue')
  },
  {
    path: '/quality',
    name: 'quality',
    component: () => import('../views/QualityView.vue')
  },
  {
    path: '/emergency',
    name: 'emergency',
    component: () => import('../views/EmergencyView.vue')
  },
  {
    path: '/cost',
    name: 'cost',
    component: () => import('../views/CostView.vue')
  },
  {
    path: '/drill',
    name: 'drill',
    component: () => import('../views/DrillView.vue')
  },
  {
    path: '/ai',
    name: 'ai',
    component: () => import('../views/AIChatView.vue')
  },
  {
    path: '/bigscreen',
    name: 'bigscreen',
    component: () => import('../views/bigscreen/BigScreenView.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router