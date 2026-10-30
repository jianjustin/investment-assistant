<script lang="ts">
	import { onMount } from "svelte";
	import { Toaster as Sonner, type ToasterProps as SonnerProps } from "svelte-sonner";
	import LoaderCircleIcon from "@lucide/svelte/icons/loader-circle";
	import CircleCheckIcon from "@lucide/svelte/icons/circle-check";
	import OctagonXIcon from "@lucide/svelte/icons/octagon-x";
	import InfoIcon from "@lucide/svelte/icons/info";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import { getTheme, onThemeChange } from "$lib/theme.js";

	let { ...restProps }: SonnerProps = $props();

	// The project owns the theme (lib/theme.ts); there is no mode-watcher.
	let theme = $state(getTheme());
	// svelte-sonner calls window.matchMedia unconditionally; where it is missing (jsdom) render nothing instead of crashing.
	const supported = typeof window !== "undefined" && typeof window.matchMedia === "function";
	onMount(() => onThemeChange((t) => (theme = t)));
</script>

{#if supported}
	<Sonner
		{theme}
		class="toaster group"
		closeButtonAriaLabel="关闭"
		containerAriaLabel="通知"
		style="--normal-bg: var(--popover); --normal-text: var(--popover-foreground); --normal-border: var(--border); --border-radius: var(--radius);"
		{...restProps}
	>
		{#snippet loadingIcon()}
			<LoaderCircleIcon class="size-4 animate-spin" />
		{/snippet}
		{#snippet successIcon()}
			<CircleCheckIcon class="size-4 text-success" />
		{/snippet}
		{#snippet errorIcon()}
			<OctagonXIcon class="size-4 text-destructive" />
		{/snippet}
		{#snippet infoIcon()}
			<InfoIcon class="size-4 text-info" />
		{/snippet}
		{#snippet warningIcon()}
			<TriangleAlertIcon class="size-4 text-warn" />
		{/snippet}
	</Sonner>
{/if}
