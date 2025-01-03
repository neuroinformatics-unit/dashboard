// Fetchers for issue & pull request data and metrics

import { Organization } from '@octokit/graphql-schema';
import { Config, Fetcher } from '..';
import { CustomOctokit } from '../lib/octokit';
import excludedRepos from '../../excluded_repos.json';

const queryForDiscussions = async (octokit: CustomOctokit, config: Config) => {
  return await octokit.graphql.paginate<{ organization: Organization }>(
    `
      query($cursor: String, $organization: String!) {
        organization(login:$organization){
          repositories(privacy:PUBLIC, first:100, isFork:false, isArchived:false, after: $cursor) {
            totalCount
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              name
              discussions {
                totalCount
              }
            }
          }
        }
      }
    `,
    {
      organization: config.organization,
    },
  );
};

const getDiscussionData = async (octokit: CustomOctokit, config: Config) => {
  const queryResult = await queryForDiscussions(octokit, config);

  const dataResult = queryResult.organization.repositories.nodes?.map(
    (node) => {
      return {
        repositoryName: node!.name,
        discussionsCount: node!.discussions.totalCount,
      };
    },
  );

  return dataResult;
};

export const addDiscussionData: Fetcher = async (result, octokit, config) => {
  const dataResult = await getDiscussionData(octokit, config);
  if (!dataResult) {
    return result;
  }

  const filteredResult = dataResult.filter(
    (repo) =>
      !(excludedRepos.includes(repo!.repositoryName) ||
        repo!.repositoryName.startsWith("slides-") ||
        repo!.repositoryName.startsWith("course-")),
  )

  for (const repo of filteredResult) {
    result.repositories[repo.repositoryName].discussionsCount =
      repo.discussionsCount;
  }

  return result;
};
