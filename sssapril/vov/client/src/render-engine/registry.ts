import type { ViewComponentProps, ViewType } from './types';

type ViewComponent = React.ComponentType<ViewComponentProps>;

const viewRegistry = new Map<ViewType, ViewComponent>();

export function registerView(type: ViewType, component: ViewComponent) {
  viewRegistry.set(type, component);
}

export function getViewComponent(type: ViewType): ViewComponent | null {
  return viewRegistry.get(type) ?? null;
}

export function getRegisteredTypes(): ViewType[] {
  return [...viewRegistry.keys()];
}
