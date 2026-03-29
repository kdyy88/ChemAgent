declare module 'smiles-drawer' {
  interface DrawerOptions {
    width?: number
    height?: number
    bondThickness?: number
    fontSizeLarge?: number
    fontSizeSmall?: number
    padding?: number
    atomVisualization?: 'default' | 'balls'
    [key: string]: unknown
  }

  class Drawer {
    constructor(options?: DrawerOptions)
    draw(tree: unknown, canvas: HTMLCanvasElement, theme?: string, inRing?: boolean): void
  }

  class SvgDrawer {
    constructor(options?: DrawerOptions)
    draw(tree: unknown, target: HTMLElement | string, theme?: string): void
  }

  function parse(
    smiles: string,
    successCallback: (tree: unknown) => void,
    errorCallback?: (err: unknown) => void,
  ): void

  const _default: {
    Drawer: typeof Drawer
    SvgDrawer: typeof SvgDrawer
    parse: typeof parse
  }

  export default _default
}
