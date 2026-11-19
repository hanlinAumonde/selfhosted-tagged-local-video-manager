import { TestBed } from '@angular/core/testing';
import { ApolloTestingController, ApolloTestingModule } from 'apollo-angular/testing';
import { Observable, Subject } from 'rxjs';
import { MockInstance } from 'vitest';

import { GqlService } from './GQL.service';
import { ToastService } from '../toast-service/toast.service';
import {
  BatchDeleteSubscriptionDocument,
  BatchResultType,
  BatchUpdateSubscriptionDocument,
  BrowseDirectoryDocument,
  DirectoryDeletionStrategy,
  GetMigrationTasksDocument,
  GetSuggestionsDocument,
  GetTopTagsAsSuggestionDocument,
  GetTopTagsDocument,
  SearchField,
  SearchInDirectoryDocument,
} from '../../core/graphql/generated/graphql';
import { ResultState } from '../../shared/models/GQL-result.model';
import { ToastType } from '../../shared/models/toast.model';
import { environment } from '../../../environments/environment';
import { aMigrationTask } from '../../../testing/migration-fixtures';
import { aBrowseNode } from '../../../testing/video-fixtures';
import { apolloAsInTheApp } from '../../../testing/apollo-testing';

/** Apollo hands results to subscribers asynchronously. */
const tick = () => vi.advanceTimersByTimeAsync(0);

/** Everything a stream emits, and whether it has completed. */
function record<T>(stream: Observable<ResultState<T>>) {
  const recorded = { results: [] as ResultState<T>[], completed: false, errored: false };
  stream.subscribe({
    next: result => recorded.results.push(result),
    complete: () => (recorded.completed = true),
    error: () => (recorded.errored = true),
  });
  return recorded;
}

const tag = (name: string, count: number) => ({ __typename: 'VideoTag', name, count });

describe('GqlService', () => {
  let service: GqlService;
  let apollo: ApolloTestingController;
  let toast: MockInstance<ToastService['emitNewToast']>;

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({ imports: [ApolloTestingModule] });
    service = TestBed.inject(GqlService);
    apollo = apolloAsInTheApp();
    toast = vi.spyOn(TestBed.inject(ToastService), 'emitNewToast').mockImplementation(() => {});
  });

  afterEach(() => vi.useRealTimers());

  const taskList = (tasks = [aMigrationTask(), aMigrationTask()]) => ({
    getMigrationTasks: { __typename: 'MigrationTaskListResult', totalCount: tasks.length, page: 1, pageSize: 10, tasks },
  });

  describe('result state', () => {
    it('reports a one-off query as loaded with the extracted data', async () => {
      /*
        Given the backend answers getMigrationTasks with two tasks
        When getMigrationTasksQuery() is subscribed
        Then it emits one result with loading false, no error and the task list as data
        And the stream completes
      */
      const answer = taskList();
      const tasks = record(service.getMigrationTasksQuery({ page: 1, pageSize: 10 }));
      await tick();

      apollo.expectOne(GetMigrationTasksDocument).flushData(answer);
      await tick();

      expect(tasks.results).toEqual([{ loading: false, error: null, data: answer.getMigrationTasks }]);
      expect(tasks.completed).toBe(true);
    });

    it('reports a watched query as loading until the backend answers', async () => {
      /*
        Given browseDirectoryQuery() is subscribed for directory "local/a"
        When the backend has not answered yet
        Then the latest result has loading true
        When the backend answers with two entries
        Then the latest result has loading false, no error and both entries as data
      */
      const listing = record(service.browseDirectoryQuery('local/a'));
      await tick();

      expect(listing.results.at(-1)?.loading).toBe(true);

      const entries = [aBrowseNode({ isDir: true, name: 'sub' }), aBrowseNode()];
      const op = apollo.expectOne(BrowseDirectoryDocument);
      expect(op.operation.variables['input'].relativePath).toBe('local/a');
      op.flushData({ browseDirectory: entries });
      await tick();

      expect(listing.results.at(-1)).toEqual({ loading: false, error: null, data: entries });
    });

    it('turns a failed request into an error result and shows an error toast', async () => {
      /*
        Given getMigrationTasksQuery() is subscribed
        When the request fails with a network error "socket closed"
        Then the stream emits one result with loading false, data null and an error mentioning "socket closed"
        And completes instead of erroring
        And an error toast mentioning "socket closed" is shown
      */
      const tasks = record(service.getMigrationTasksQuery({ page: 1, pageSize: 10 }));
      await tick();

      apollo.expectOne(GetMigrationTasksDocument).networkError(new Error('socket closed'));
      await tick();

      expect(tasks.results).toEqual([
        { loading: false, data: null, error: expect.stringContaining('socket closed') },
      ]);
      expect(tasks.completed).toBe(true);
      expect(tasks.errored).toBe(false);
      expect(toast).toHaveBeenCalledExactlyOnceWith(expect.stringContaining('socket closed'), ToastType.Error);
    });

    it('shows no toast for a successful request', async () => {
      /*
        Given getMigrationTasksQuery() is subscribed
        When the backend answers successfully
        Then no toast is shown
      */
      record(service.getMigrationTasksQuery({ page: 1, pageSize: 10 }));
      await tick();

      apollo.expectOne(GetMigrationTasksDocument).flushData(taskList());
      await tick();

      expect(toast).not.toHaveBeenCalled();
    });
  });

  describe('getSuggestionsQuery', () => {
    let typed: Subject<string | null>;

    beforeEach(() => (typed = new Subject<string | null>()));

    const suggestionsFor = (field: SearchField) => record(service.getSuggestionsQuery(typed, field));

    it('asks the backend once for the last keyword typed within the debounce window', async () => {
      /*
        Given suggestions are requested for the Name field
        When the user types "a", "ab" and "abc" less than 500ms apart
        And 500ms pass after the last keystroke
        Then exactly one getSuggestions request is sent, for keyword "abc" and field Name
        And the suggestions it returns are emitted
      */
      const suggestions = suggestionsFor(SearchField.Name);

      typed.next('a');
      await vi.advanceTimersByTimeAsync(300);
      typed.next('ab');
      await vi.advanceTimersByTimeAsync(300);
      typed.next('abc');
      await vi.advanceTimersByTimeAsync(499);
      apollo.verify();
      await vi.advanceTimersByTimeAsync(1);

      const op = apollo.expectOne(GetSuggestionsDocument);
      expect(op.operation.variables['input']).toEqual({ keyword: { keyWord: 'abc' }, suggestionType: SearchField.Name });
      op.flushData({ getSuggestions: ['abcd', 'abcde'] });
      await tick();

      expect(suggestions.results.at(-1)?.data).toEqual(['abcd', 'abcde']);
    });

    it('does not ask again when the keyword settles on the same value', async () => {
      /*
        Given suggestions were already fetched for Author keyword "bob"
        When the user types "bo" and then "bob" again, and 500ms pass
        Then no new request is sent
      */
      const suggestions = suggestionsFor(SearchField.Author);
      typed.next('bob');
      await vi.advanceTimersByTimeAsync(500);
      apollo.expectOne(GetSuggestionsDocument).flushData({ getSuggestions: ['bobby'] });
      await tick();

      typed.next('bo');
      await vi.advanceTimersByTimeAsync(100);
      typed.next('bob');
      await vi.advanceTimersByTimeAsync(500);

      // A repeat would go to the network under the app's policies: verify() catches it.
      expect(suggestions.results).toHaveLength(1);
      apollo.verify();
    });

    it('offers the top tags when the Tag input is empty', async () => {
      /*
        Given suggestions are requested for the Tag field
        When the input is cleared and 500ms pass
        Then the top tags are requested instead of getSuggestions
        And their names are emitted as suggestions
      */
      const suggestions = suggestionsFor(SearchField.Tag);

      typed.next('');
      await vi.advanceTimersByTimeAsync(500);

      apollo.expectOne(GetTopTagsAsSuggestionDocument).flushData({
        getTopTags: [{ __typename: 'VideoTag', name: '4k' }, { __typename: 'VideoTag', name: 'todo' }],
      });
      await tick();

      expect(suggestions.results.at(-1)?.data).toEqual(['4k', 'todo']);
      apollo.verify();
    });

    it('offers nothing for an empty Name input without asking the backend', async () => {
      /*
        Given suggestions are requested for the Name field
        When the input is cleared and 500ms pass
        Then an empty suggestion list is emitted
        And no request is sent
      */
      const suggestions = suggestionsFor(SearchField.Name);

      typed.next('');
      await vi.advanceTimersByTimeAsync(500);

      expect(suggestions.results.at(-1)?.data).toEqual([]);
      apollo.verify();
    });

    it('skips keywords longer than the field allows', async () => {
      /*
        Given suggestions are requested for the Tag field
        When the user types a keyword one character longer than the tag length limit and 500ms pass
        Then no request is sent
      */
      const suggestions = suggestionsFor(SearchField.Tag);

      typed.next('x'.repeat(environment.VALIDATION_RULES.TAG_MAX_LENGTH + 1));
      await vi.advanceTimersByTimeAsync(500);

      expect(suggestions.results).toEqual([]);
      apollo.verify();
    });

    it('drops the answer for a keyword the user has already typed past', async () => {
      /*
        Given a getSuggestions request for keyword "ab" is still pending
        When the user types "abc" and 500ms pass
        And the backend answers both requests
        Then only the suggestions for "abc" are emitted
      */
      const suggestions = suggestionsFor(SearchField.Name);
      typed.next('ab');
      await vi.advanceTimersByTimeAsync(500);
      const stale = apollo.expectOne(GetSuggestionsDocument);

      typed.next('abc');
      await vi.advanceTimersByTimeAsync(500);
      const current = apollo.expectOne(GetSuggestionsDocument);
      stale.flushData({ getSuggestions: ['ab-stale'] });
      current.flushData({ getSuggestions: ['abc-current'] });
      await tick();

      expect(suggestions.results.map(r => r.data)).toEqual([['abc-current']]);
    });
  });

  describe('request and response shaping', () => {
    it('drops tags without a name or count and applies the limit', async () => {
      /*
        Given the backend returns five tags, one without a name and one with a zero count
        When getTopTagsQuery(2) is subscribed
        Then the data holds only the first two complete tags, in the backend's order
      */
      const tags = record(service.getTopTagsQuery(2));
      await tick();

      apollo.expectOne(GetTopTagsDocument).flushData({
        getTopTags: [tag('', 9), tag('4k', 8), tag('unused', 0), tag('todo', 5), tag('hd', 3)],
      });
      await tick();

      expect(tags.results.at(-1)?.data).toEqual([tag('4k', 8), tag('todo', 5)]);
    });

    it('leaves blank directory-search fields out of the request', async () => {
      /*
        Given a search in directory "local/a" with an empty name, no author and tag "4k"
        When searchInDirectoryQuery() is subscribed
        Then the request carries the directory and tag "4k"
        And carries no name keyword and no author keyword
      */
      record(service.searchInDirectoryQuery('local/a', '', undefined, ['4k']));
      await tick();

      const input = apollo.expectOne(SearchInDirectoryDocument).operation.variables['input'];
      expect(input.path).toEqual({ relativePath: 'local/a' });
      expect(input.tags).toEqual(['4k']);
      expect(input.name.keyWord).toBeUndefined();
      expect(input.author.keyWord).toBeUndefined();
    });

    it('flattens batch progress into status, result type and message', async () => {
      /*
        Given batchUpdateVideosSubscription() is subscribed for videos "v1" and "v2" with author "bob"
        When the backend pushes a progress frame and then a final frame with a Success result and a message
        Then the request carries both video ids and author "bob"
        And the emitted data is the status of each frame, with the result type and message of the final one
      */
      const progress = record(service.batchUpdateVideosSubscription({
        relativePath: { relativePath: 'local/a' },
        videoIds: ['v1', 'v2'],
        author: 'bob',
      }));
      await tick();

      const op = apollo.expectOne(BatchUpdateSubscriptionDocument);
      expect(op.operation.variables['input']).toMatchObject({ videoIds: ['v1', 'v2'], author: 'bob' });
      const frame = (status: string, result: { resultType: BatchResultType; message: string } | null) => ({
        batchUpdateSubscription: {
          __typename: 'BatchOperationStatus',
          status,
          result: result && { __typename: 'VideosBatchOperationResult', ...result },
        },
      });
      op.flushData(frame('1/2 updated', null));
      await tick();
      op.flushData(frame('done', { resultType: BatchResultType.Success, message: '2 videos updated' }));
      await tick();

      expect(progress.results.map(r => r.data)).toEqual([
        { status: '1/2 updated', result: { resultType: undefined, message: undefined } },
        { status: 'done', result: { resultType: BatchResultType.Success, message: '2 videos updated' } },
      ]);
    });

    it('sends a folder disposition only for a directory delete that has one', async () => {
      /*
        Given batchDeleteVideosSubscription() is subscribed once for videos "v1" and "v2"
        And once for directory "local/a" with disposition DeleteFolder
        Then the first request carries no directoryDeletion
        And the second carries DeleteFolder
      */
      record(service.batchDeleteVideosSubscription({ relativePath: { relativePath: 'local/a' }, videoIds: ['v1', 'v2'] }));
      record(service.batchDeleteVideosSubscription({
        videoIds: [],
        relativePath: { relativePath: 'local/a' },
        directoryDeletion: DirectoryDeletionStrategy.DeleteFolder,
      }));
      await tick();

      const [byIds, byDirectory] = apollo.match(BatchDeleteSubscriptionDocument).map(op => op.operation.variables['input']);
      expect(byIds.videoIds).toEqual(['v1', 'v2']);
      expect(byIds.directoryDeletion).toBeUndefined();
      expect(byDirectory.relativePath).toEqual({ relativePath: 'local/a' });
      expect(byDirectory.directoryDeletion).toBe(DirectoryDeletionStrategy.DeleteFolder);
    });
  });
});
