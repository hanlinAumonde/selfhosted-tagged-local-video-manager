export const environment = {
    production: true,
    backend_api: "",
    backend_ws_api: `ws://${window.location.host}`,
    video_stream_api: "/video/stream/",
    homepage_api: "/home",
    searchpage_api: "/search",
    management_api: "/management",
    videopage_api: "/video",
    videopage_thumbnail_api: "/video/thumbnail",
    pageListSize: 5,
    refreshKey: "_refresh_key",
    scrollKey: "_scroll_position",
    videoUpdateChannel: "video-updates",
    VIEW_MODE_STORAGE_KEY: "file-browser-view-mode",
    containerIds: {
        rootMainContainerId: "root-main-container"
    },
    visibleTagsCountInManagement: 3,
    VALIDATION_RULES:{
        NAME_MAX_LENGTH: 200,
        AUTHOR_MAX_LENGTH: 50,
        INTRODUCTION_MAX_LENGTH: 2000,
        TAG_MAX_LENGTH: 30,
        MAX_TAGS_COUNT: 50,
        PAGE_NUMBER_MIN: 1,
        PAGE_NUMBER_MAX: 10000,
        SERIES_NAME_MAX_LENGTH: 100,
    },
    ERROR_TOAST_SETTINGS: {
        MAX_TOASTS: 4,
        AUTO_DISMISS_MS: 10000,
        EXIT_ANIMATION_MS: 300,
    }
} as const;