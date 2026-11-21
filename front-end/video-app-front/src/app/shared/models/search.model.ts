import { VideoSortOption } from "../../core/graphql/generated/graphql"

export type SearchPageParam = {
    sortBy?: VideoSortOption,
    tags?: string[],
    title?: string,
    author?: string,
    currentPage?: number
}