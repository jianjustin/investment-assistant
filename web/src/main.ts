import { mount } from 'svelte'
import App from './app.svelte'
import './styles/app.css'

mount(App, { target: document.querySelector('#app')! })
